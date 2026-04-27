"""Inbox: accumulate sources during the day, digest later.

Two-file model:
  inbox.jsonl        — pending items, always open for append
  inbox.processing.jsonl — items currently being digested (locked)

digest moves pending → processing at start.
add always writes to inbox.jsonl — never blocked.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

INBOX_PATH = Path("~/.local/state/paperworlds/textread/inbox.jsonl")
PROCESSING_PATH = Path("~/.local/state/paperworlds/textread/inbox.processing.jsonl")
LOCK_PATH = Path("~/.local/state/paperworlds/textread/inbox.lock")


@dataclass
class InboxEntry:
    source: str
    type: str       # "url" | "pdf" | "md"
    title: str
    cache_key: str
    added_at: str


def _path() -> Path:
    return INBOX_PATH.expanduser()


def _processing_path() -> Path:
    return PROCESSING_PATH.expanduser()


def _lock_path() -> Path:
    return LOCK_PATH.expanduser()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _read_jsonl(path: Path) -> list[InboxEntry]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            entries.append(InboxEntry(**{k: d[k] for k in InboxEntry.__dataclass_fields__}))
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
    return entries


def _write_jsonl(path: Path, entries: list[InboxEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(e.__dict__) + "\n" for e in entries),
        encoding="utf-8",
    )


def lock_info() -> tuple[int, str] | None:
    """Return (pid, started_at) if a live digest lock exists, else None.

    Stale locks (dead PID) are auto-removed.
    """
    p = _lock_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        pid = int(data["pid"])
        started_at = data["started_at"]
    except (json.JSONDecodeError, KeyError, ValueError):
        p.unlink(missing_ok=True)
        return None
    if not _pid_alive(pid):
        p.unlink(missing_ok=True)
        _processing_path().unlink(missing_ok=True)
        return None
    return pid, started_at


def add(source: str, type_: str, title: str, cache_key: str) -> None:
    """Append one entry to the pending inbox. Always open — never blocked."""
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
    """Return pending (not yet digested) inbox entries."""
    return _read_jsonl(_path())


def list_processing() -> list[InboxEntry]:
    """Return items currently locked for digestion."""
    info = lock_info()
    if info is None:
        return []
    return _read_jsonl(_processing_path())


def start_digest() -> list[InboxEntry]:
    """Move all pending entries to processing. Returns the locked entries.

    Calling start_digest() while a live lock exists raises RuntimeError.
    """
    info = lock_info()
    if info is not None:
        raise RuntimeError(f"Digest already running (pid {info[0]}, started {info[1]})")

    pending = list_entries()
    if not pending:
        return []

    # Write processing file first, then clear pending
    _write_jsonl(_processing_path(), pending)
    _path().unlink(missing_ok=True)

    # Write lock
    _lock_path().parent.mkdir(parents=True, exist_ok=True)
    _lock_path().write_text(json.dumps({
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }), encoding="utf-8")

    return pending


def finish_digest(clear: bool = False) -> None:
    """Release the lock. If not clearing, move processing items back to pending."""
    if not clear:
        # Restore undigested items to the front of the inbox
        processing = _read_jsonl(_processing_path())
        remaining = _read_jsonl(_path())
        if processing or remaining:
            _write_jsonl(_path(), processing + remaining)

    _processing_path().unlink(missing_ok=True)
    _lock_path().unlink(missing_ok=True)


def clear() -> None:
    """Remove the pending inbox file entirely."""
    _path().unlink(missing_ok=True)
