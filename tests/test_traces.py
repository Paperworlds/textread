"""Tests for textread.traces — shared SQLite trace log."""
from __future__ import annotations

import pytest

import textread.traces as traces_mod


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(traces_mod, "_DB_PATH", tmp_path / "traces.db")


def _record(**kw):
    defaults = dict(
        tool="textread", operation="evaluate",
        ref="https://example.com", model="claude-haiku-4-5-20251001",
        backend="sdk", verdict="worth_reading", score=80,
        latency_ms=1000, in_tokens=512, out_tokens=128,
    )
    traces_mod.record(**{**defaults, **kw})


def test_record_and_recent():
    _record(ref="https://a.com", verdict="worth_reading")
    _record(ref="https://b.com", verdict="skip")
    rows = traces_mod.recent()
    assert len(rows) == 2
    assert rows[0]["ref"] == "https://b.com"  # most recent first


def test_recent_limit():
    for i in range(10):
        _record(ref=f"https://example.com/{i}")
    assert len(traces_mod.recent(limit=3)) == 3


def test_recent_filter_tool():
    _record(tool="textread", operation="evaluate")
    _record(tool="textmap", operation="query_node")
    rows = traces_mod.recent(tool="textmap")
    assert len(rows) == 1
    assert rows[0]["tool"] == "textmap"


def test_recent_filter_operation():
    _record(operation="evaluate")
    _record(operation="fetch")
    rows = traces_mod.recent(operation="fetch")
    assert len(rows) == 1
    assert rows[0]["operation"] == "fetch"


def test_stats_verdicts():
    _record(verdict="worth_reading")
    _record(verdict="worth_reading")
    _record(verdict="skip")
    s = traces_mod.stats()
    assert s["total"] == 3
    assert s["by_verdict"]["worth_reading"] == 2
    assert s["by_verdict"]["skip"] == 1


def test_stats_scoped_to_tool():
    _record(tool="textread", operation="evaluate")
    _record(tool="textmap", operation="query_node")
    s = traces_mod.stats(tool="textread")
    assert s["total"] == 1
    assert s["by_operation"] == {"evaluate": 1}


def test_stats_tokens():
    _record(in_tokens=100, out_tokens=50)
    _record(in_tokens=200, out_tokens=80)
    s = traces_mod.stats()
    assert s["total_in_tokens"] == 300
    assert s["total_out_tokens"] == 130


def test_stats_none_tokens():
    _record(in_tokens=None, out_tokens=None)
    s = traces_mod.stats()
    assert s["total_in_tokens"] is None


def test_stats_empty_db():
    s = traces_mod.stats()
    assert s["total"] == 0
    assert s["by_verdict"] == {}
    assert s["by_operation"] == {}


def test_meta_kwargs_stored_as_json():
    import json
    _record(operation="fetch", reason="robots blocked", cache_hit=False)
    rows = traces_mod.recent(operation="fetch")
    assert rows[0]["meta"] is not None
    meta = json.loads(rows[0]["meta"])
    assert meta["reason"] == "robots blocked"
    assert meta["cache_hit"] is False


def test_record_cli_no_tokens():
    _record(backend="cli", in_tokens=None, out_tokens=None)
    rows = traces_mod.recent()
    assert rows[0]["backend"] == "cli"
    assert rows[0]["in_tokens"] is None


def test_idempotent_schema_creation():
    _record()
    _record()
    assert traces_mod.stats()["total"] == 2
