"""Reading log: append entries to ~/.local/paperworlds/textread/log.yaml."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from textread.agent import Mapping

LOG_PATH = Path("~/.local/paperworlds/textread/log.yaml").expanduser()


def append_entry(
    url: str,
    mapping: Mapping,
    cache_path: Path,
    log_path: Path | None = None,
) -> None:
    """Append a reading log entry to the log YAML file.

    Args:
        url: The URL that was read.
        mapping: The agent Mapping result.
        cache_path: Absolute path to the cache directory.
        log_path: Path to the log file. If None, use LOG_PATH. Override exists
                  solely for test isolation.

    Writes:
        One entry appended to log_path as a YAML list of mappings.
        If log_path doesn't exist, creates it with one entry.
        If log_path is malformed, logs warning and starts fresh.
    """
    if log_path is None:
        log_path = LOG_PATH

    # Load existing entries or start fresh
    entries = []
    if log_path.exists():
        try:
            data = yaml.safe_load(log_path.read_text())
            entries = data if isinstance(data, list) else []
        except yaml.YAMLError:
            # Degradation: warn and start fresh
            print("[WARN] log.yaml is malformed — creating a fresh log")
            entries = []

    # Build new entry
    entry = {
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "url": url,
        "verdict": mapping.verdict,
        "score": mapping.score,
        "tags": mapping.tags,
        "mapping_path": str(cache_path / "mapping.yaml"),
    }

    # Append and write back
    entries.append(entry)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(yaml.dump(entries, default_flow_style=False))
