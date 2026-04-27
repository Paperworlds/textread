"""Digest persistence: save, list, review."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import click

DIGESTS_DIR = Path("~/.local/state/paperworlds/textread/digests")


@dataclass
class DigestInfo:
    id: str          # filename stem, e.g. "2026-04-27" or "2026-04-27-2"
    path: Path
    status: str      # "pending" | "reviewed"
    source_count: int
    saved_at: str    # date portion of id


def _dir() -> Path:
    return DIGESTS_DIR.expanduser()


def _state_path(digest_path: Path) -> Path:
    return digest_path.with_suffix(".state")


_STATUS_COLORS = {"reviewed": "green", "discarded": "red", "pending": "yellow"}


def _source_count(path: Path) -> int:
    """Count bullet lines under ## Sources in the digest file."""
    try:
        in_sources = False
        count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() == "## Sources":
                in_sources = True
                continue
            if in_sources:
                if line.startswith("## "):
                    break
                if line.startswith("- "):
                    count += 1
        return count
    except OSError:
        return 0


def list_digests() -> list[DigestInfo]:
    """Return all saved digests, newest first."""
    d = _dir()
    if not d.exists():
        return []
    infos = []
    for p in sorted(d.glob("*.md"), reverse=True):
        state_file = _state_path(p)
        raw_state = state_file.read_text().strip() if state_file.exists() else ""
        status = raw_state if raw_state in {"reviewed", "discarded"} else "pending"
        infos.append(DigestInfo(
            id=p.stem,
            path=p,
            status=status,
            source_count=_source_count(p),
            saved_at=p.stem[:10],
        ))
    return infos


def save(output: str, items: list) -> Path:
    """Write digest markdown to DIGESTS_DIR and return the path."""
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    candidate = d / f"{date_str}.md"
    counter = 2
    while candidate.exists():
        candidate = d / f"{date_str}-{counter}.md"
        counter += 1

    sources_block = "\n".join(f"- [{e.type}] {e.source}" for e, _ in items)
    full_content = f"# Digest — {date_str}\n\n## Sources\n\n{sources_block}\n\n---\n\n{output}\n"
    candidate.write_text(full_content, encoding="utf-8")
    return candidate


def _mark_state(digest_id: str, state: str) -> Path | None:
    d = _dir()
    candidate = d / f"{digest_id}.md"
    if not candidate.exists():
        return None
    _state_path(candidate).write_text(f"{state}\n", encoding="utf-8")
    return candidate


def mark_reviewed(digest_id: str) -> Path | None:
    return _mark_state(digest_id, "reviewed")


def mark_discarded(digest_id: str) -> Path | None:
    return _mark_state(digest_id, "discarded")


@click.group(name="digests")
def digests_group():
    """List and review saved digests."""


@digests_group.command("list")
def list_cmd():
    """List all saved digests with status."""
    infos = list_digests()
    if not infos:
        click.echo("No digests saved yet.")
        return
    for d in infos:
        color = _STATUS_COLORS.get(d.status, "white")
        status_tag = click.style(d.status, fg=color)
        click.echo(f"  {d.id}  [{status_tag}]  {d.source_count} source(s)")


@digests_group.command("show")
@click.argument("digest_id")
def show_cmd(digest_id: str):
    """Print the content of a saved digest."""
    d = _dir() / f"{digest_id}.md"
    if not d.exists():
        click.echo(f"[ERROR] No digest found: {digest_id}", err=True)
        raise SystemExit(1)
    click.echo_via_pager(d.read_text(encoding="utf-8"))


@digests_group.command("review")
@click.argument("digest_id")
def review_cmd(digest_id: str):
    """Mark a digest as reviewed."""
    result = mark_reviewed(digest_id)
    if result is None:
        click.echo(f"[ERROR] No digest found: {digest_id}", err=True)
        raise SystemExit(1)
    click.echo(f"[DIGEST] marked reviewed → {digest_id}")


@digests_group.command("discard")
@click.argument("digest_id")
def discard_cmd(digest_id: str):
    """Mark a digest as discarded (not worth keeping)."""
    result = mark_discarded(digest_id)
    if result is None:
        click.echo(f"[ERROR] No digest found: {digest_id}", err=True)
        raise SystemExit(1)
    click.echo(f"[DIGEST] marked discarded → {digest_id}")
