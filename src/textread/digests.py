"""Digest persistence: save, list, review."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import click

DIGESTS_DIR = Path("~/.local/paperworlds/textread/digests")


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


def _source_urls(path: Path) -> list[str]:
    """Return the URL strings from each '- [type] url' bullet under ## Sources."""
    try:
        urls: list[str] = []
        in_sources = False
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() == "## Sources":
                in_sources = True
                continue
            if in_sources:
                if line.startswith("## "):
                    break
                if line.startswith("- "):
                    # Format: "- [type] url"
                    parts = line.split("] ", 1)
                    if len(parts) == 2:
                        urls.append(parts[1].strip())
        return urls
    except OSError:
        return []


def _source_count(path: Path) -> int:
    """Count bullet lines under ## Sources in the digest file."""
    return len(_source_urls(path))


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


@digests_group.command("audit")
@click.option("--min-count", type=int, default=2, help="Only show domains with at least N appearances (default: 2)")
def audit_cmd(min_count: int):
    """Per-domain discard rate across all digests — what sources keep wasting time?"""
    from urllib.parse import urlparse

    infos = list_digests()
    if not infos:
        click.echo("No digests saved yet.")
        return

    # domain -> {"reviewed": n, "discarded": n, "pending": n}
    by_domain: dict[str, dict[str, int]] = {}
    for d in infos:
        for url in _source_urls(d.path):
            try:
                netloc = urlparse(url).netloc.lower()
            except ValueError:
                continue
            if netloc.startswith("www."):
                netloc = netloc[4:]
            if not netloc:
                continue
            bucket = by_domain.setdefault(netloc, {"reviewed": 0, "discarded": 0, "pending": 0})
            bucket[d.status] = bucket.get(d.status, 0) + 1

    rows = []
    for domain, counts in by_domain.items():
        total = counts["reviewed"] + counts["discarded"] + counts["pending"]
        decided = counts["reviewed"] + counts["discarded"]
        if total < min_count:
            continue
        discard_rate = (counts["discarded"] / decided * 100) if decided else 0.0
        rows.append((discard_rate, total, domain, counts))

    if not rows:
        click.echo(f"No domains with ≥{min_count} appearances yet.")
        return

    rows.sort(key=lambda r: (-r[0], -r[1], r[2]))

    click.echo(f"{'domain':<40} {'n':>4}  {'rev':>4} {'dis':>4} {'pen':>4}  {'discard%':>9}")
    click.echo("-" * 76)
    for discard_rate, total, domain, counts in rows:
        rate_str = f"{discard_rate:.0f}%" if (counts["reviewed"] + counts["discarded"]) else "—"
        color = "red" if discard_rate >= 50 else ("yellow" if discard_rate >= 25 else "green")
        click.echo(
            f"{domain:<40} {total:>4}  "
            f"{counts['reviewed']:>4} {counts['discarded']:>4} {counts['pending']:>4}  "
            f"{click.style(rate_str.rjust(9), fg=color)}"
        )


@digests_group.command("stats")
def stats_cmd():
    """Aggregate counts, acceptance rate, and trailing 30-day trend."""
    from datetime import date, timedelta

    infos = list_digests()
    if not infos:
        click.echo("No digests saved yet.")
        return

    counts = {"reviewed": 0, "discarded": 0, "pending": 0}
    for d in infos:
        counts[d.status] = counts.get(d.status, 0) + 1

    total = sum(counts.values())
    decided = counts["reviewed"] + counts["discarded"]
    accept_rate = (counts["reviewed"] / decided * 100) if decided else 0.0

    cutoff = (date.today() - timedelta(days=30)).isoformat()
    recent = [d for d in infos if d.saved_at >= cutoff]
    recent_decided = sum(1 for d in recent if d.status in {"reviewed", "discarded"})
    recent_discarded = sum(1 for d in recent if d.status == "discarded")
    recent_rate = (recent_discarded / recent_decided * 100) if recent_decided else 0.0

    click.echo(f"Total digests:    {total}")
    for status in ("reviewed", "discarded", "pending"):
        color = _STATUS_COLORS.get(status, "white")
        click.echo(f"  {click.style(status.ljust(10), fg=color)}  {counts[status]}")
    click.echo()
    click.echo(f"Acceptance rate:  {accept_rate:.0f}%  (reviewed / decided, all time)")
    click.echo(f"30-day discard:   {recent_rate:.0f}%  ({recent_discarded}/{recent_decided} decided in last 30d)")
