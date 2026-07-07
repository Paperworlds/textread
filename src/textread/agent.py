"""Agent layer: call Anthropic API and return a structured Mapping."""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import sys
from typing import Any

import anthropic

from textread.context import ReadContext

MAX_CONTENT_CHARS = 80_000

MODEL_ALIASES: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5",
    "opus": "claude-opus-4-5",
}

VALID_VERDICTS = {"worth_reading", "skim", "skip"}

_SCHEMA = {
    "verdict": "worth_reading | skim | skip",
    "score": "integer 0-100",
    "reason": "one-line explanation for this specific user",
    "summary": "<=200 word summary lensed through user context",
    "key_points": ["string", "..."],
    "connects_to": ["project name from user context", "..."],
    "tags": ["string", "..."],
}


class AgentError(Exception):
    """Raised on parse failure or invalid verdict."""


@dataclasses.dataclass
class Mapping:
    verdict: str
    score: int
    reason: str
    summary: str
    key_points: list[str]
    connects_to: list[str]
    tags: list[str]


def _build_system_prompt(context: ReadContext) -> str:
    projects_lines = "; ".join(
        f"{p.name}: {p.summary} [current: {', '.join(p.current) if p.current else 'none'}]"
        for p in context.projects
    ) if context.projects else "none"

    downweight = ", ".join(context.filters.get("downweight", [])) or "none"
    stack = ", ".join(context.stack) if context.stack else "none"

    from textread import learnings as learnings_mod
    from textread.config import load as load_config
    cfg = load_config()
    learnings_block = learnings_mod.summarize_for_agent(
        learnings_mod.load_all(cfg.learnings_path)
    )
    learnings_section = f"\n{learnings_block}\n" if learnings_block else ""

    return (
        "You are a relevance filter for a developer.\n"
        "User context:\n"
        f"  Role: {context.role or 'unspecified'}\n"
        f"  Stack: {stack}\n"
        f"  Projects: {projects_lines}\n"
        f"  Downweight: {downweight}\n"
        f"{learnings_section}"
        "Return ONLY valid JSON matching this schema — no markdown, no prose:\n"
        + json.dumps(_SCHEMA, indent=2)
    )


def _parse_mapping(raw_text: str) -> Mapping:
    """Parse and validate a JSON string into a Mapping. Raises AgentError on failure."""
    try:
        parsed: dict[str, Any] = json.loads(raw_text)
        verdict = parsed["verdict"]
        if verdict not in VALID_VERDICTS:
            raise AgentError(raw_text)
        field_names = {f.name for f in dataclasses.fields(Mapping)}
        return Mapping(**{k: parsed[k] for k in field_names})
    except AgentError:
        raise
    except (json.JSONDecodeError, KeyError):
        raise AgentError(raw_text)


def _resolve_profile_env(profile: str | None) -> dict[str, str]:
    """Return env overrides for the given profile name, or {} if none.
    Raises AgentError if textaccounts is not installed but a profile was requested."""
    if profile is None:
        return {}
    try:
        from textaccounts.api import env_for_profile, list_profiles  # type: ignore[import]
    except ImportError:
        raise AgentError(
            "--profile / default_profile requires the textaccounts package. "
            "Install with: uv tool install --with textaccounts textread  (or `uv add textaccounts` in this repo)"
        )
    profiles = list_profiles()
    # list_profiles() returns list[str] per textaccounts-api-v0-2 spec
    if profile not in profiles:
        raise AgentError(f"Unknown profile: {profile}")
    return env_for_profile(profile)


def _sanitize(text: str) -> str:
    """Strip null bytes and CR characters that could corrupt subprocess args."""
    return text.replace("\x00", "").replace("\r", "")


def _evaluate_sdk(
    url: str,
    raw: str,
    context: ReadContext,
    model: str,
) -> Mapping:
    model_id = MODEL_ALIASES.get(model, model)

    if len(raw) > MAX_CONTENT_CHARS:
        raw = raw[:MAX_CONTENT_CHARS]

    system_prompt = _build_system_prompt(context)
    user_msg = f"URL: {url}\n\nContent:\n{raw}"

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model_id,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw_text: str = response.content[0].text
    return _parse_mapping(raw_text)


def _evaluate_cli(
    url: str,
    raw: str,
    context: ReadContext,
    model: str,
    profile_env: dict[str, str] | None = None,
) -> Mapping:
    if shutil.which("claude") is None:
        raise AgentError("claude binary not found — install Claude Code or use --no-agent")

    model_id = MODEL_ALIASES.get(model, model)
    system = _sanitize(_build_system_prompt(context))
    user_msg = _sanitize(f"URL: {url}\n\nContent:\n{raw[:MAX_CONTENT_CHARS]}")
    env = {**os.environ, **(profile_env or {})}

    result = subprocess.run(
        ["claude", "-p", user_msg, "--system-prompt", system,
         "--model", model_id, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if result.returncode != 0:
        raise AgentError(result.stderr.strip() or "claude -p exited non-zero")

    return _parse_mapping(result.stdout.strip())


_DIGEST_SYSTEM = """\
You are a research synthesis assistant.
The user has collected several items during the day and wants to discuss them.

Your output must be markdown with exactly these three sections:

## Item Summaries
For each item, write a 2-3 sentence summary — what it is and why it matters.

## Themes & Connections
Identify 2-4 recurring themes or surprising connections across the items.

## Brainstorm
List 4-6 concrete questions or ideas the user could explore next, sparked by what they collected.
"""


def _digest_sdk(system: str, user_msg: str, model_id: str) -> str:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model_id,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text


def _digest_cli(system: str, user_msg: str, model_id: str, profile_env: dict) -> str:
    if shutil.which("claude") is None:
        raise AgentError("claude binary not found — install Claude Code or use --no-agent")
    env = {**os.environ, **(profile_env or {})}
    result = subprocess.run(
        ["claude", "-p", _sanitize(user_msg), "--system-prompt", _sanitize(system),
         "--model", model_id, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    if result.returncode != 0:
        raise AgentError(result.stderr.strip() or "claude -p exited non-zero")
    return result.stdout.strip()


def digest(
    items: list[tuple],
    model: str = "haiku",
    backend: str = "sdk",
    profile: str | None = None,
) -> str:
    """Synthesize inbox items into a research digest (markdown string).

    Args:
        items: List of (InboxEntry, text_content) pairs.
        model: Model alias or raw ID.
        backend: "sdk" or "cli".
        profile: textaccounts profile for CLI backend.

    Returns:
        Markdown string with Item Summaries, Themes & Connections, Brainstorm.
    """
    model_id = MODEL_ALIASES.get(model, model)
    chars_per_item = max(4000, MAX_CONTENT_CHARS // len(items))

    parts: list[str] = []
    for entry, text in items:
        truncated = text[:chars_per_item]
        parts.append(f"### [{entry.type.upper()}] {entry.source}\n\n{truncated}")

    user_msg = (
        f"Here are {len(items)} item(s) I collected today:\n\n---\n\n"
        + "\n\n---\n\n".join(parts)
    )

    if backend == "cli":
        profile_env = _resolve_profile_env(profile)
        return _digest_cli(_DIGEST_SYSTEM, user_msg, model_id, profile_env)
    if profile is not None:
        print("[WARN] --profile has no effect with sdk backend", file=sys.stderr)
    return _digest_sdk(_DIGEST_SYSTEM, user_msg, model_id)


def evaluate(
    url: str,
    raw: str,
    context: ReadContext,
    model: str = "haiku",
    backend: str = "sdk",
    profile: str | None = None,
) -> Mapping:
    """Call the configured agent backend and return a structured Mapping.

    Args:
        url: The source URL.
        raw: Raw text content of the page.
        context: User reading context.
        model: Model alias ("haiku", "sonnet", "opus") or raw model ID.
        backend: "sdk" (default) or "cli" (shells out to `claude -p`).
        profile: textaccounts profile name for CLI backend env injection.

    Returns:
        Mapping dataclass with verdict, score, and summary fields.

    Raises:
        AgentError: If the response cannot be parsed or verdict is invalid.
    """
    if backend == "cli":
        profile_env = _resolve_profile_env(profile)
        return _evaluate_cli(url, raw, context, model, profile_env)
    if profile is not None:
        print("[WARN] --profile has no effect with sdk backend", file=sys.stderr)
    return _evaluate_sdk(url, raw, context, model)
