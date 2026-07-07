"""Tests for textread.log module."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from textread.agent import Mapping
from textread.log import append_entry


@pytest.fixture
def fake_mapping() -> Mapping:
    """Return a fake Mapping for testing."""
    return Mapping(
        verdict="worth_reading",
        score=87,
        reason="Relevant to current project",
        summary="A useful article about Python.",
        key_points=["point one", "point two"],
        connects_to=["myproject"],
        tags=["python", "mcp"],
    )


def test_r01_r02_appends_entry(tmp_path, fake_mapping):
    """R01/R02: append_entry writes entry with all required keys."""
    log_path = tmp_path / "log.yaml"
    cache_path = tmp_path / "cache" / "article-a1b2c3"
    url = "https://example.com/article"

    append_entry(url, fake_mapping, cache_path, log_path=log_path)

    assert log_path.exists()
    data = yaml.safe_load(log_path.read_text())
    assert isinstance(data, list)
    assert len(data) == 1

    entry = data[0]
    assert entry["url"] == url
    assert entry["verdict"] == "worth_reading"
    assert entry["score"] == 87
    assert entry["tags"] == ["python", "mcp"]
    assert entry["mapping_path"] == str(cache_path / "mapping.yaml")
    assert "date" in entry


def test_r03_creates_file_if_missing(tmp_path, fake_mapping):
    """R03: append_entry creates log.yaml if missing."""
    log_path = tmp_path / "log.yaml"
    cache_path = tmp_path / "cache" / "article-a1b2c3"
    url = "https://example.com/article"

    assert not log_path.exists()
    append_entry(url, fake_mapping, cache_path, log_path=log_path)

    assert log_path.exists()
    data = yaml.safe_load(log_path.read_text())
    assert isinstance(data, list)
    assert len(data) == 1


def test_r04_appends_without_overwriting(tmp_path, fake_mapping):
    """R04: append_entry appends to existing list without overwriting."""
    log_path = tmp_path / "log.yaml"
    cache_path1 = tmp_path / "cache" / "article-a1b2c3"
    cache_path2 = tmp_path / "cache" / "article-d4e5f6"
    url1 = "https://example.com/article1"
    url2 = "https://example.com/article2"

    # First append
    append_entry(url1, fake_mapping, cache_path1, log_path=log_path)

    # Second append
    append_entry(url2, fake_mapping, cache_path2, log_path=log_path)

    data = yaml.safe_load(log_path.read_text())
    assert len(data) == 2
    assert data[0]["url"] == url1
    assert data[1]["url"] == url2


def test_r05_valid_yaml_list(tmp_path, fake_mapping):
    """R05: log.yaml is valid YAML that parses as a list."""
    log_path = tmp_path / "log.yaml"
    cache_path1 = tmp_path / "cache" / "article-a1b2c3"
    cache_path2 = tmp_path / "cache" / "article-d4e5f6"
    url1 = "https://example.com/article1"
    url2 = "https://example.com/article2"

    append_entry(url1, fake_mapping, cache_path1, log_path=log_path)
    append_entry(url2, fake_mapping, cache_path2, log_path=log_path)

    # Parse the raw YAML
    raw = log_path.read_text()
    data = yaml.safe_load(raw)

    assert isinstance(data, list)
    assert len(data) == 2
    assert all(isinstance(entry, dict) for entry in data)


def test_r06_no_save_flag_skips_log(tmp_path, fake_mapping):
    """R06: read command without --save doesn't write log.yaml."""
    from textread.cli import read_cmd
    from unittest.mock import patch, MagicMock
    import click.testing

    log_path = tmp_path / "log.yaml"

    # Mock the entire fetch and agent chain
    with patch("textread.cli.fetch.pull") as mock_pull, \
         patch("textread.cli.cache.get_markdown") as mock_get_md, \
         patch("textread.cli.agent.evaluate") as mock_eval, \
         patch("textread.cli.cache.write_mapping") as mock_write, \
         patch("textread.cli.load_config") as mock_load_cfg, \
         patch("textread.log.LOG_PATH", log_path):

        mock_pull.return_value = None
        mock_get_md.return_value = "article text"
        mock_eval.return_value = fake_mapping

        runner = click.testing.CliRunner()
        result = runner.invoke(read_cmd, ["https://example.com"])

        # Should succeed (result.exit_code == 0 or non-save doesn't fail)
        # and log.yaml should NOT be created
        assert not log_path.exists(), "log.yaml should not exist without --save"


def test_degradation_corrupt_yaml(tmp_path, fake_mapping):
    """Degradation: handle corrupt YAML gracefully."""
    log_path = tmp_path / "log.yaml"
    cache_path = tmp_path / "cache" / "article-a1b2c3"
    url = "https://example.com/article"

    # Write malformed YAML
    log_path.write_text("not: valid: yaml: [")

    # Capture stderr to check for warning
    with patch("builtins.print") as mock_print:
        append_entry(url, fake_mapping, cache_path, log_path=log_path)

        # Should print warning
        mock_print.assert_called_once()
        assert "malformed" in mock_print.call_args[0][0].lower()

    # File should be valid YAML now with one entry
    data = yaml.safe_load(log_path.read_text())
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["url"] == url


def test_date_format_iso8601(tmp_path, fake_mapping):
    """Entry date field is ISO 8601 format (YYYY-MM-DD)."""
    log_path = tmp_path / "log.yaml"
    cache_path = tmp_path / "cache" / "article-a1b2c3"
    url = "https://example.com/article"

    append_entry(url, fake_mapping, cache_path, log_path=log_path)

    data = yaml.safe_load(log_path.read_text())
    entry = data[0]

    date_str = entry["date"]
    # Should match YYYY-MM-DD pattern
    parts = date_str.split("-")
    assert len(parts) == 3
    assert len(parts[0]) == 4  # year
    assert len(parts[1]) == 2  # month
    assert len(parts[2]) == 2  # day
