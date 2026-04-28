"""Unit tests for the inbox module."""
from __future__ import annotations

import json
import os

import pytest

import textread.inbox as inbox


@pytest.fixture(autouse=True)
def patch_inbox_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, "INBOX_PATH", tmp_path / "inbox.jsonl")
    monkeypatch.setattr(inbox, "PROCESSING_PATH", tmp_path / "inbox.processing.jsonl")
    monkeypatch.setattr(inbox, "LOCK_PATH", tmp_path / "inbox.lock")


def test_empty_inbox_returns_empty_list():
    assert inbox.list_entries() == []


def test_add_and_list_single_entry():
    inbox.add("https://example.com", "url", "Example", "https://example.com")
    entries = inbox.list_entries()
    assert len(entries) == 1
    e = entries[0]
    assert e.source == "https://example.com"
    assert e.type == "url"
    assert e.title == "Example"
    assert e.cache_key == "https://example.com"
    assert "T" in e.added_at


def test_add_multiple_entries_preserves_order():
    inbox.add("https://a.com", "url", "A", "https://a.com")
    inbox.add("/path/doc.pdf", "pdf", "doc", "file:///path/doc.pdf")
    inbox.add("/notes.md", "md", "notes", "file:///notes.md")
    entries = inbox.list_entries()
    assert len(entries) == 3
    assert entries[0].source == "https://a.com"
    assert entries[1].type == "pdf"
    assert entries[2].type == "md"


def test_clear_removes_all_entries():
    inbox.add("https://example.com", "url", "Ex", "https://example.com")
    inbox.clear()
    assert inbox.list_entries() == []


def test_clear_on_empty_inbox_is_noop():
    inbox.clear()
    assert inbox.list_entries() == []


def test_malformed_line_is_skipped(tmp_path, monkeypatch):
    p = tmp_path / "inbox2.jsonl"
    p.write_text(
        '{"source":"ok","type":"url","title":"ok","cache_key":"ok","added_at":"2026-01-01T00:00:00Z"}\n'
        'not-valid-json\n'
        '{"source":"also-ok","type":"pdf","title":"ok","cache_key":"ok","added_at":"2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(inbox, "INBOX_PATH", p)
    entries = inbox.list_entries()
    assert len(entries) == 2
    assert entries[0].source == "ok"
    assert entries[1].source == "also-ok"


def test_start_digest_moves_entries_to_processing():
    inbox.add("https://a.com", "url", "A", "https://a.com")
    inbox.add("https://b.com", "url", "B", "https://b.com")
    locked = inbox.start_digest()
    assert len(locked) == 2
    assert inbox.list_entries() == []          # pending is empty
    assert len(inbox.list_processing()) == 2   # items are locked


def test_finish_digest_clear_removes_processing():
    inbox.add("https://a.com", "url", "A", "https://a.com")
    inbox.start_digest()
    inbox.finish_digest(clear=True)
    assert inbox.list_entries() == []
    assert inbox.list_processing() == []
    assert not inbox.LOCK_PATH.expanduser().exists()


def test_finish_digest_no_clear_restores_entries():
    inbox.add("https://a.com", "url", "A", "https://a.com")
    inbox.start_digest()
    inbox.finish_digest(clear=False)
    entries = inbox.list_entries()
    assert len(entries) == 1
    assert entries[0].source == "https://a.com"


def test_add_during_digest_goes_to_pending():
    inbox.add("https://a.com", "url", "A", "https://a.com")
    inbox.start_digest()
    inbox.add("https://b.com", "url", "B", "https://b.com")  # added while locked
    assert len(inbox.list_processing()) == 1   # only a.com locked
    assert len(inbox.list_entries()) == 1      # b.com is pending


def test_lock_info_returns_none_when_no_lock():
    assert inbox.lock_info() is None


def test_lock_info_returns_pid_while_locked():
    inbox.add("https://a.com", "url", "A", "https://a.com")
    inbox.start_digest()
    info = inbox.lock_info()
    assert info is not None
    assert info[0] == os.getpid()
    inbox.finish_digest(clear=True)


def test_stale_lock_is_auto_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, "LOCK_PATH", tmp_path / "inbox.lock")
    lock_file = (tmp_path / "inbox.lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text(json.dumps({"pid": 999999999, "started_at": "2026-01-01T00:00:00Z"}))
    assert inbox.lock_info() is None
    assert not lock_file.exists()


def test_stale_lock_recovers_stranded_processing_items():
    """Regression: a crashed digest left items in inbox.processing.jsonl;
    the next lock_info() call must restore them to the pending inbox,
    not silently delete them."""
    inbox.add("https://a.com", "url", "A", "https://a.com")
    inbox.add("https://b.com", "url", "B", "https://b.com")
    inbox.start_digest()
    # Simulate a crashed process: rewrite the lock to a dead PID,
    # leaving the processing file intact (no finish_digest called).
    inbox.LOCK_PATH.expanduser().write_text(
        json.dumps({"pid": 999999999, "started_at": "2026-01-01T00:00:00Z"})
    )
    assert inbox.lock_info() is None
    entries = inbox.list_entries()
    assert {e.source for e in entries} == {"https://a.com", "https://b.com"}
    assert inbox.list_processing() == []
