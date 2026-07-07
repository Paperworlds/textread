"""Shared SQLite trace log for all paperworlds tools.

All tools write to ~/.local/paperworlds/traces.db with a common schema.
The `tool` and `operation` columns identify the source; `meta` holds a
JSON blob for tool-specific fields that don't fit the common columns.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path("~/.local/paperworlds/traces.db")

_DDL = """
CREATE TABLE IF NOT EXISTS traces (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    tool        TEXT    NOT NULL,
    operation   TEXT    NOT NULL,
    ref         TEXT,
    model       TEXT,
    backend     TEXT,
    verdict     TEXT,
    score       INTEGER,
    latency_ms  INTEGER,
    in_tokens   INTEGER,
    out_tokens  INTEGER,
    meta        TEXT
);
CREATE INDEX IF NOT EXISTS traces_ts        ON traces(ts);
CREATE INDEX IF NOT EXISTS traces_tool      ON traces(tool);
CREATE INDEX IF NOT EXISTS traces_operation ON traces(operation);
CREATE INDEX IF NOT EXISTS traces_ref       ON traces(ref);
"""


def _db_path() -> Path:
    return _DB_PATH.expanduser()


@contextmanager
def _connect():
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_DDL)
        yield conn
        conn.commit()
    finally:
        conn.close()


def record(
    tool: str,
    operation: str,
    ref: str | None = None,
    model: str | None = None,
    backend: str | None = None,
    verdict: str | None = None,
    score: int | None = None,
    latency_ms: int | None = None,
    in_tokens: int | None = None,
    out_tokens: int | None = None,
    **meta,
) -> None:
    """Write one trace row. Extra kwargs go into the meta JSON blob."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta_json = json.dumps(meta) if meta else None
    with _connect() as conn:
        conn.execute(
            "INSERT INTO traces "
            "(ts, tool, operation, ref, model, backend, verdict, score, "
            "latency_ms, in_tokens, out_tokens, meta) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, tool, operation, ref, model, backend, verdict, score,
             latency_ms, in_tokens, out_tokens, meta_json),
        )


def recent(limit: int = 50, tool: str | None = None,
           operation: str | None = None) -> list[sqlite3.Row]:
    """Return recent rows, optionally filtered by tool and/or operation."""
    clauses, params = [], []
    if tool:
        clauses.append("tool = ?")
        params.append(tool)
    if operation:
        clauses.append("operation = ?")
        params.append(operation)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with _connect() as conn:
        return conn.execute(
            f"SELECT * FROM traces {where} ORDER BY ts DESC LIMIT ?", params
        ).fetchall()


def stats(tool: str | None = None) -> dict:
    """Aggregate stats, optionally scoped to one tool."""
    where = "WHERE tool = ?" if tool else ""
    params = [tool] if tool else []
    with _connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM traces {where}", params
        ).fetchone()[0]
        by_operation = {
            r["operation"]: r["n"]
            for r in conn.execute(
                f"SELECT operation, COUNT(*) AS n FROM traces {where} "
                "GROUP BY operation ORDER BY n DESC", params
            ).fetchall()
        }
        verdict_filter = ("AND" if where else "WHERE") + " verdict IS NOT NULL"
        by_verdict = {
            r["verdict"]: r["n"]
            for r in conn.execute(
                f"SELECT verdict, COUNT(*) AS n FROM traces {where} "
                f"{verdict_filter} GROUP BY verdict ORDER BY n DESC", params
            ).fetchall()
        }
        model_filter = ("AND" if where else "WHERE") + " model IS NOT NULL"
        by_model = {
            r["model"]: r["n"]
            for r in conn.execute(
                f"SELECT model, COUNT(*) AS n FROM traces {where} "
                f"{model_filter} GROUP BY model ORDER BY n DESC", params
            ).fetchall()
        }
        avg_latency = conn.execute(
            f"SELECT ROUND(AVG(latency_ms)) FROM traces {where}", params
        ).fetchone()[0]
        token_totals = conn.execute(
            f"SELECT SUM(in_tokens), SUM(out_tokens) FROM traces {where}", params
        ).fetchone()
    return {
        "total": total,
        "by_operation": by_operation,
        "by_verdict": by_verdict,
        "by_model": by_model,
        "avg_latency_ms": avg_latency,
        "total_in_tokens": token_totals[0],
        "total_out_tokens": token_totals[1],
    }
