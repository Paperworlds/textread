"""Inbox: accumulate sources during the day, digest later."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

INBOX_PATH = Path("~/.local/state/paperworlds/textread/inbox.jsonl")


@dataclass
class InboxEntry:
    source: str
    type: str       # "url" | "pdf" | "md"
    title: str
    cache_key: str
    added_at: str


def _path() -> Path:
    return INBOX_PATH.expanduser()


def add(source: str, type_: str, title: str, cache_key: str) -> None:
    """Append one entry to the inbox."""
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "source": source,
        "type": type_,
        "title": title,
        "cache_key": cache_key,
        "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def list_entries() -> list[InboxEntry]:
    """Return all pending inbox entries in insertion order."""
    p = _path()
    if not p.exists():
        return []
    entries = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            entries.append(InboxEntry(**d))
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
    return entries


def clear() -> None:
    """Remove the inbox file entirely."""
    p = _path()
    if p.exists():
        p.unlink()
