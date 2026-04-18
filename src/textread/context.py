import dataclasses
import os
from pathlib import Path

import click
import yaml

from textread.config import load as load_config


_KNOWN_CONTEXT_FIELDS = {"role", "stack", "projects", "filters"}


@dataclasses.dataclass
class Project:
    name: str
    summary: str = ""
    current: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class ReadContext:
    role: str = ""
    stack: list = dataclasses.field(default_factory=list)
    projects: list = dataclasses.field(default_factory=list)
    filters: dict = dataclasses.field(default_factory=dict)


def _context_path() -> Path:
    cfg = load_config()
    return Path(cfg.context_path).expanduser()


def load() -> ReadContext:
    path = _context_path()
    if not path.exists():
        return ReadContext()
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        print("[WARN] read-context.yaml is malformed — using defaults")
        return ReadContext()
    known = {k: v for k, v in data.items() if k in _KNOWN_CONTEXT_FIELDS}
    projects_raw = known.pop("projects", []) or []
    projects = [
        Project(**{k: v for k, v in p.items() if k in {"name", "summary", "current"}})
        if isinstance(p, dict) else Project(name=str(p))
        for p in projects_raw
    ]
    return ReadContext(projects=projects, **known)


def save(ctx: ReadContext) -> None:
    path = _context_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(dataclasses.asdict(ctx), default_flow_style=False))


@click.group(name="context")
def context_group():
    """Manage read context."""


@context_group.command("show")
def show():
    """Print current context YAML to stdout."""
    ctx = load()
    click.echo(yaml.dump(dataclasses.asdict(ctx), default_flow_style=False), nl=False)


@context_group.command("edit")
def edit():
    """Open context file in $EDITOR."""
    path = _context_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump(dataclasses.asdict(ReadContext()), default_flow_style=False))
    editor = os.environ.get("EDITOR", "vi")
    click.edit(filename=str(path), editor=editor)
