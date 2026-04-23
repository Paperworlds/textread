"""CLI composition root — wires all modules into the Click group hierarchy."""
from __future__ import annotations

import dataclasses
import subprocess
import sys
from pathlib import Path

import click
import yaml

from textread import __version__
from textread import agent, cache, context, fetch
from textread.agent import AgentError, Mapping
from textread.cache import cache_group
from textread.config import load as load_config
from textread.context import ReadContext, context_group
from textread.fetch import FetchBlocked, FetchError
from textread.log import append_entry


def _load_context(ctx_path: str | None) -> ReadContext:
    if ctx_path is not None:
        path = Path(ctx_path)
        if not path.exists():
            click.echo(f"[ERROR] Context file not found: {ctx_path}", err=True)
            sys.exit(1)
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            click.echo(f"[WARN] Context file malformed: {ctx_path} — using defaults", err=True)
            return ReadContext()
        known = {k: v for k, v in data.items() if k in {"role", "stack", "projects", "filters"}}
        projects_raw = known.pop("projects", []) or []
        from textread.context import Project
        projects = [
            Project(**{k: v for k, v in p.items() if k in {"name", "summary", "current"}})
            if isinstance(p, dict) else Project(name=str(p))
            for p in projects_raw
        ]
        return ReadContext(projects=projects, **known)
    return context.load()


def _verdict_line(mapping: Mapping) -> str:
    return f"{mapping.verdict.upper()}  ({mapping.score}/100)  {mapping.reason}"


def _print_output(mapping: Mapping, deep: bool) -> None:
    if deep:
        click.echo(yaml.dump(dataclasses.asdict(mapping), default_flow_style=False), nl=False)
    else:
        click.echo(_verdict_line(mapping))


class _CacheProxy:
    def __init__(self, cfg):
        self._cfg = cfg

    def exists(self, url: str) -> bool:
        return cache.exists(url, self._cfg)


def _is_pdf(source: str) -> bool:
    """Return True if source looks like a PDF by extension."""
    if source.startswith(("http://", "https://")):
        return source.lower().split("?")[0].endswith(".pdf")
    return Path(source).suffix.lower() == ".pdf"


def _run_url_pipeline(url, model, ctx_path, refresh, deep, save, no_agent, via_cli, profile, cfg):
    if via_cli and no_agent:
        click.echo("[ERROR] --via-cli and --no-agent are mutually exclusive", err=True)
        sys.exit(1)

    model = model or cfg.default_model
    ctx = _load_context(ctx_path)
    run_agent = cfg.agent_enabled and not no_agent
    backend = "cli" if via_cli else cfg.agent_backend
    profile = profile or cfg.default_profile

    try:
        result = fetch.pull(url, refresh=refresh, cache=_CacheProxy(cfg))
    except FetchBlocked as e:
        click.echo(f"[WARN] Blocked by robots.txt: {e}", err=True)
        sys.exit(1)
    except FetchError as e:
        click.echo(f"[ERROR] Fetch failed: {e}", err=True)
        sys.exit(1)

    if result is not None:
        cache.put(url, result, cfg)

    raw = cache.get_markdown(url, cfg)

    if not run_agent:
        click.echo(f"[CACHED] {url}")
        return

    try:
        mapping = agent.evaluate(url, raw, ctx, model, backend=backend, profile=profile)
    except AgentError as e:
        click.echo(f"[ERROR] {e}", err=True)
        sys.exit(1)

    cache.write_mapping(url, dataclasses.asdict(mapping), cfg)
    if save:
        append_entry(url, mapping, cache.path(url, cfg))
    _print_output(mapping, deep)


def _run_pdf_pipeline(source, model, ctx_path, refresh, deep, save, no_agent, via_cli, profile, pdf_backend, pages, cfg):
    if via_cli and no_agent:
        click.echo("[ERROR] --via-cli and --no-agent are mutually exclusive", err=True)
        sys.exit(1)

    model = model or cfg.default_model
    ctx = _load_context(ctx_path)
    run_agent = cfg.agent_enabled and not no_agent
    agent_backend = "cli" if via_cli else cfg.agent_backend
    profile = profile or cfg.default_profile
    pdf_backend = pdf_backend or cfg.pdf_backend

    if source.startswith(("http://", "https://")):
        cache_key = source
    else:
        cache_key = Path(source).expanduser().resolve().as_uri()

    if not refresh and cache.exists(cache_key, cfg):
        pass  # cache hit — skip extraction
    else:
        try:
            result = fetch.fetch_pdf(source, pages=pages, backend=pdf_backend)
        except FetchError as e:
            click.echo(f"[ERROR] {e}", err=True)
            sys.exit(1)
        cache.put(cache_key, result, cfg)

    raw = cache.get_markdown(cache_key, cfg)

    if not run_agent:
        click.echo(f"[CACHED] {cache_key}")
        return

    try:
        mapping = agent.evaluate(cache_key, raw, ctx, model, backend=agent_backend, profile=profile)
    except AgentError as e:
        click.echo(f"[ERROR] {e}", err=True)
        sys.exit(1)

    cache.write_mapping(cache_key, dataclasses.asdict(mapping), cfg)
    if save:
        append_entry(cache_key, mapping, cache.path(cache_key, cfg))
    _print_output(mapping, deep)


try:
    _git_hash = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        stderr=subprocess.DEVNULL, text=True,
        cwd=Path(__file__).parent,
    ).strip()
    _version_str = f"{__version__} ({_git_hash})"
except Exception:
    _version_str = __version__


@click.group()
@click.version_option(_version_str, "--version", "-V", prog_name="textread")
def main():
    """Context-aware link reader."""


@main.command(name="url")
@click.argument("url")
@click.option("--model", default=None, help="Model alias (haiku/sonnet/opus) or raw model ID.")
@click.option("--context", "ctx_path", default=None, type=click.Path(), help="Path to context YAML file.")
@click.option("--refresh", is_flag=True, default=False, help="Bypass cache and re-fetch.")
@click.option("--deep", is_flag=True, default=False, help="Print full mapping YAML.")
@click.option("--save", is_flag=True, default=False, help="Save mapping to read list.")
@click.option("--no-agent", "no_agent", is_flag=True, default=False, help="Fetch and cache only — skip the agent call.")
@click.option("--via-cli", "via_cli", is_flag=True, default=False, help="Use claude CLI backend instead of Anthropic SDK.")
@click.option("--profile", default=None, help="textaccounts profile for claude -p calls.")
def url_cmd(url, model, ctx_path, refresh, deep, save, no_agent, via_cli, profile):
    """Fetch a web URL, run agent, print verdict."""
    cfg = load_config()
    _run_url_pipeline(url, model, ctx_path, refresh, deep, save, no_agent, via_cli, profile, cfg)


@main.command(name="pdf")
@click.argument("source")
@click.option("--backend", "pdf_backend", type=click.Choice(["native", "marker"]), default=None,
              help="PDF extraction backend (default: native).")
@click.option("--pages", default=None, help="Page range, e.g. 1-5 or 3.")
@click.option("--model", default=None, help="Model alias (haiku/sonnet/opus) or raw model ID.")
@click.option("--context", "ctx_path", default=None, type=click.Path(), help="Path to context YAML file.")
@click.option("--refresh", is_flag=True, default=False, help="Re-extract even if already cached.")
@click.option("--deep", is_flag=True, default=False, help="Print full mapping YAML.")
@click.option("--save", is_flag=True, default=False, help="Save mapping to read list.")
@click.option("--no-agent", "no_agent", is_flag=True, default=False, help="Extract and cache only — skip the agent call.")
@click.option("--via-cli", "via_cli", is_flag=True, default=False, help="Use claude CLI backend instead of Anthropic SDK.")
@click.option("--profile", default=None, help="textaccounts profile for claude -p calls.")
def pdf_cmd(source, pdf_backend, pages, model, ctx_path, refresh, deep, save, no_agent, via_cli, profile):
    """Convert a PDF (local path or URL), run agent, print verdict."""
    cfg = load_config()
    _run_pdf_pipeline(source, model, ctx_path, refresh, deep, save, no_agent, via_cli, profile, pdf_backend, pages, cfg)


@main.command(name="read")
@click.argument("source")
@click.option("--model", default=None, help="Model alias (haiku/sonnet/opus) or raw model ID.")
@click.option("--context", "ctx_path", default=None, type=click.Path(), help="Path to context YAML file.")
@click.option("--refresh", is_flag=True, default=False, help="Bypass cache and re-fetch/re-extract.")
@click.option("--deep", is_flag=True, default=False, help="Print full mapping YAML.")
@click.option("--save", is_flag=True, default=False, help="Save mapping to read list.")
@click.option("--no-agent", "no_agent", is_flag=True, default=False, help="Fetch/extract and cache only — skip the agent call.")
@click.option("--via-cli", "via_cli", is_flag=True, default=False, help="Use claude CLI backend instead of Anthropic SDK.")
@click.option("--profile", default=None, help="textaccounts profile for claude -p calls.")
def read_cmd(source, model, ctx_path, refresh, deep, save, no_agent, via_cli, profile):
    """Auto-detect source type (URL or PDF) and dispatch to the right pipeline."""
    cfg = load_config()
    if _is_pdf(source):
        click.echo(f"[READ] pdf → {source}", err=True)
        _run_pdf_pipeline(source, model, ctx_path, refresh, deep, save, no_agent, via_cli, profile, None, None, cfg)
    else:
        click.echo(f"[READ] url → {source}", err=True)
        _run_url_pipeline(source, model, ctx_path, refresh, deep, save, no_agent, via_cli, profile, cfg)


@main.command(name="remap")
@click.argument("url")
@click.option("--model", default=None, help="Model alias (haiku/sonnet/opus) or raw model ID.")
@click.option("--context", "ctx_path", default=None, type=click.Path(), help="Path to context YAML file.")
@click.option("--deep", is_flag=True, default=False, help="Print full mapping YAML.")
@click.option("--no-agent", "no_agent", is_flag=True, default=False, help="Not applicable for remap.")
@click.option("--via-cli", "via_cli", is_flag=True, default=False, help="Use claude CLI backend instead of Anthropic SDK.")
@click.option("--profile", default=None, help="textaccounts profile for claude -p calls.")
def remap_cmd(url, model, ctx_path, deep, no_agent, via_cli, profile):
    """Re-run agent on cached content and overwrite mapping.yaml."""
    if no_agent:
        click.echo("[ERROR] --no-agent has no effect on remap", err=True)
        sys.exit(1)

    cfg = load_config()
    model = model or cfg.default_model
    ctx = _load_context(ctx_path)
    backend = "cli" if via_cli else cfg.agent_backend
    profile = profile or cfg.default_profile

    if not cache.exists(url, cfg):
        click.echo(f"[ERROR] No cache entry for {url} — run textread read {url} first", err=True)
        sys.exit(1)

    raw = cache.get_markdown(url, cfg)

    try:
        mapping = agent.evaluate(url, raw, ctx, model, backend=backend, profile=profile)
    except AgentError as e:
        click.echo(f"[ERROR] {e}", err=True)
        sys.exit(1)

    cache.write_mapping(url, dataclasses.asdict(mapping), cfg)
    _print_output(mapping, deep)


_COMPLETION_PATHS = {
    "fish": Path("~/.config/fish/completions/textread.fish"),
    "bash": Path("~/.local/share/bash-completion/completions/textread"),
    "zsh": Path("~/.zfunc/_textread"),
}


@main.command(name="install")
@click.option("--shell", type=click.Choice(["fish", "bash", "zsh"]), default=None,
              help="Shell to install completions for (default: auto-detect).")
def install_cmd(shell: str | None):
    """Install shell completions for fish, bash, or zsh."""
    import os

    if shell is None:
        shell_path = os.environ.get("SHELL", "")
        if "fish" in shell_path:
            shell = "fish"
        elif "zsh" in shell_path:
            shell = "zsh"
        elif "bash" in shell_path:
            shell = "bash"
        else:
            click.echo("[ERROR] Could not detect shell. Use --shell fish|bash|zsh", err=True)
            sys.exit(1)

    env = {**os.environ, "_TEXTREAD_COMPLETE": f"{shell}_source"}
    result = subprocess.run(["textread"], env=env, capture_output=True, text=True)
    if not result.stdout.strip():
        click.echo(f"[ERROR] Failed to generate {shell} completions", err=True)
        sys.exit(1)

    target = _COMPLETION_PATHS[shell].expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result.stdout)
    click.echo(f"Completions written to {target}")


main.add_command(context_group, "context")
main.add_command(cache_group, "cache")
