"""Agent layer: call Anthropic API and return a structured Mapping."""
from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
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

    return (
        "You are a relevance filter for a developer.\n"
        "User context:\n"
        f"  Role: {context.role or 'unspecified'}\n"
        f"  Stack: {stack}\n"
        f"  Projects: {projects_lines}\n"
        f"  Downweight: {downweight}\n"
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
) -> Mapping:
    if shutil.which("claude") is None:
        raise AgentError("claude binary not found — install Claude Code or use --no-agent")

    model_id = MODEL_ALIASES.get(model, model)
    system = _sanitize(_build_system_prompt(context))
    user_msg = _sanitize(f"URL: {url}\n\nContent:\n{raw[:MAX_CONTENT_CHARS]}")

    result = subprocess.run(
        ["claude", "-p", user_msg, "--system", system,
         "--model", model_id, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise AgentError(result.stderr.strip() or "claude -p exited non-zero")

    return _parse_mapping(result.stdout.strip())


def evaluate(
    url: str,
    raw: str,
    context: ReadContext,
    model: str = "haiku",
    backend: str = "sdk",
) -> Mapping:
    """Call the configured agent backend and return a structured Mapping.

    Args:
        url: The source URL.
        raw: Raw text content of the page.
        context: User reading context.
        model: Model alias ("haiku", "sonnet", "opus") or raw model ID.
        backend: "sdk" (default) or "cli" (shells out to `claude -p`).

    Returns:
        Mapping dataclass with verdict, score, and summary fields.

    Raises:
        AgentError: If the response cannot be parsed or verdict is invalid.
    """
    if backend == "cli":
        return _evaluate_cli(url, raw, context, model)
    return _evaluate_sdk(url, raw, context, model)
