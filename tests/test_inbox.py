"""Unit tests for the inbox module."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import textread.inbox as inbox


@pytest.fixture(autouse=True)
def patch_inbox_path(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, "INBOX_PATH", tmp_path / "inbox.jsonl")


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
    assert "T" in e.added_at  # ISO timestamp


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
    inbox.clear()  # should not raise
    assert inbox.list_entries() == []


def test_malformed_line_is_skipped(tmp_path, monkeypatch):
    p = tmp_path / "inbox.jsonl"
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
