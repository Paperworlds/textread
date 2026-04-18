"""CLI composition root — wires all modules into the Click group hierarchy."""
from __future__ import annotations

import dataclasses
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
    """Load context from path override or default config location."""
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
    """Thin wrapper so fetch.pull can call cache.exists(url) with config bound."""

    def __init__(self, cfg):
        self._cfg = cfg

    def exists(self, url: str) -> bool:
        return cache.exists(url, self._cfg)


@click.group()
@click.version_option(__version__)
def main():
    """Context-aware link reader."""


@main.command(name="read")
@click.argument("url")
@click.option("--model", default=None, help="Model alias (haiku/sonnet/opus) or raw model ID.")
@click.option("--context", "ctx_path", default=None, type=click.Path(), help="Path to context YAML file.")
@click.option("--refresh", is_flag=True, default=False, help="Bypass cache and re-fetch from network.")
@click.option("--deep", is_flag=True, default=False, help="Print full mapping YAML instead of verdict line.")
@click.option("--save", is_flag=True, default=False, help="Save mapping to read list.")
@click.option("--no-agent", "no_agent", is_flag=True, default=False, help="Fetch and cache only — skip the agent call.")
@click.option("--via-cli", "via_cli", is_flag=True, default=False, help="Use claude CLI backend instead of Anthropic SDK.")
def read_cmd(url: str, model: str | None, ctx_path: str | None, refresh: bool, deep: bool, save: bool, no_agent: bool, via_cli: bool):
    """Fetch URL, run agent, write mapping.yaml, print verdict."""
    if via_cli and no_agent:
        click.echo("[ERROR] --via-cli and --no-agent are mutually exclusive", err=True)
        sys.exit(1)

    cfg = load_config()
    model = model or cfg.default_model
    ctx = _load_context(ctx_path)
    run_agent = cfg.agent_enabled and not no_agent
    backend = "cli" if via_cli else cfg.agent_backend

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
        mapping = agent.evaluate(url, raw, ctx, model, backend=backend)
    except AgentError as e:
        click.echo(f"[ERROR] {e}", err=True)
        sys.exit(1)

    cache.write_mapping(url, dataclasses.asdict(mapping), cfg)

    if save:
        append_entry(url, mapping, cache.path(url, cfg))

    _print_output(mapping, deep)


@main.command(name="remap")
@click.argument("url")
@click.option("--model", default=None, help="Model alias (haiku/sonnet/opus) or raw model ID.")
@click.option("--context", "ctx_path", default=None, type=click.Path(), help="Path to context YAML file.")
@click.option("--deep", is_flag=True, default=False, help="Print full mapping YAML instead of verdict line.")
@click.option("--no-agent", "no_agent", is_flag=True, default=False, help="Not applicable for remap.")
@click.option("--via-cli", "via_cli", is_flag=True, default=False, help="Use claude CLI backend instead of Anthropic SDK.")
def remap_cmd(url: str, model: str | None, ctx_path: str | None, deep: bool, no_agent: bool, via_cli: bool):
    """Re-run agent on cached content and overwrite mapping.yaml."""
    if no_agent:
        click.echo("[ERROR] --no-agent has no effect on remap", err=True)
        sys.exit(1)

    cfg = load_config()
    model = model or cfg.default_model
    ctx = _load_context(ctx_path)
    backend = "cli" if via_cli else cfg.agent_backend

    if not cache.exists(url, cfg):
        click.echo(f"[ERROR] No cache entry for {url} — run textread read {url} first", err=True)
        sys.exit(1)

    raw = cache.get_markdown(url, cfg)

    try:
        mapping = agent.evaluate(url, raw, ctx, model, backend=backend)
    except AgentError as e:
        click.echo(f"[ERROR] {e}", err=True)
        sys.exit(1)

    cache.write_mapping(url, dataclasses.asdict(mapping), cfg)
    _print_output(mapping, deep)


main.add_command(context_group, "context")
main.add_command(cache_group, "cache")
