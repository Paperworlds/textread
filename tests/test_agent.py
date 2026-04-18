"""Tests for textread.agent (all API calls mocked)."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from textread.agent import AgentError, Mapping, _parse_mapping, _sanitize, evaluate
from textread.context import Project, ReadContext

_VALID_JSON = json.dumps({
    "verdict": "worth_reading",
    "score": 85,
    "reason": "Directly relevant to current stack",
    "summary": "A useful article.",
    "key_points": ["point one", "point two"],
    "connects_to": ["myproject"],
    "tags": ["python", "testing"],
})


def mock_response(text: str) -> MagicMock:
    """Return a mock Anthropic client whose messages.create returns text."""
    content_block = MagicMock()
    content_block.text = text

    message = MagicMock()
    message.content = [content_block]

    client = MagicMock()
    client.messages.create.return_value = message
    return client


@patch("textread.agent.anthropic.Anthropic")
def test_r01_single_api_call(mock_cls):
    client = mock_response(_VALID_JSON)
    mock_cls.return_value = client

    evaluate("https://example.com", "some content", ReadContext())

    client.messages.create.assert_called_once()


@patch("textread.agent.anthropic.Anthropic")
def test_r02_returns_mapping(mock_cls):
    client = mock_response(_VALID_JSON)
    mock_cls.return_value = client

    result = evaluate("https://example.com", "some content", ReadContext())

    assert isinstance(result, Mapping)
    assert result.verdict == "worth_reading"
    assert result.score == 85
    assert result.reason == "Directly relevant to current stack"


@patch("textread.agent.anthropic.Anthropic")
def test_r03_model_alias_haiku(mock_cls):
    client = mock_response(_VALID_JSON)
    mock_cls.return_value = client

    evaluate("https://example.com", "content", ReadContext(), model="haiku")

    _, kwargs = client.messages.create.call_args
    assert kwargs["model"] == "claude-haiku-4-5-20251001"


@patch("textread.agent.anthropic.Anthropic")
def test_r03_model_alias_sonnet(mock_cls):
    client = mock_response(_VALID_JSON)
    mock_cls.return_value = client

    evaluate("https://example.com", "content", ReadContext(), model="sonnet")

    _, kwargs = client.messages.create.call_args
    assert kwargs["model"] == "claude-sonnet-4-5"


@patch("textread.agent.anthropic.Anthropic")
def test_r04_truncates_long_content(mock_cls):
    client = mock_response(_VALID_JSON)
    mock_cls.return_value = client

    long_content = "x" * 100_000
    evaluate("https://example.com", long_content, ReadContext())

    _, kwargs = client.messages.create.call_args
    user_message = kwargs["messages"][0]["content"]
    # The content portion after "Content:\n" should be at most 80_000 chars
    content_part = user_message.split("Content:\n", 1)[1]
    assert len(content_part) <= 80_000


@patch("textread.agent.anthropic.Anthropic")
def test_r05_bad_json_raises_agent_error(mock_cls):
    client = mock_response("not json")
    mock_cls.return_value = client

    with pytest.raises(AgentError):
        evaluate("https://example.com", "content", ReadContext())


@patch("textread.agent.anthropic.Anthropic")
def test_r06_empty_context_no_crash(mock_cls):
    client = mock_response(_VALID_JSON)
    mock_cls.return_value = client

    result = evaluate("https://example.com", "content", ReadContext())

    assert isinstance(result, Mapping)


@patch("textread.agent.anthropic.Anthropic")
def test_r07_invalid_verdict_raises(mock_cls):
    bad_json = json.dumps({
        "verdict": "banana",
        "score": 50,
        "reason": "reason",
        "summary": "summary",
        "key_points": [],
        "connects_to": [],
        "tags": [],
    })
    client = mock_response(bad_json)
    mock_cls.return_value = client

    with pytest.raises(AgentError):
        evaluate("https://example.com", "content", ReadContext())


# ---------------------------------------------------------------------------
# CLI backend tests (010)
# ---------------------------------------------------------------------------

def _make_subprocess_result(stdout: str, returncode: int = 0, stderr: str = "") -> MagicMock:
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


def test_r01_cli_backend_calls_subprocess(monkeypatch):
    """CLI backend calls subprocess and returns correct Mapping."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")

    called_args = []

    def fake_run(args, **kwargs):
        called_args.extend(args)
        return _make_subprocess_result(_VALID_JSON)

    monkeypatch.setattr("subprocess.run", fake_run)

    result = evaluate("https://example.com", "some content", ReadContext(), backend="cli")

    assert isinstance(result, Mapping)
    assert result.verdict == "worth_reading"
    assert "--system" in called_args


def test_r02_cli_backend_no_binary(monkeypatch):
    """AgentError raised when claude binary is not on PATH."""
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(AgentError, match="claude binary not found"):
        evaluate("https://example.com", "content", ReadContext(), backend="cli")


def test_r03_cli_backend_nonzero_exit(monkeypatch):
    """AgentError raised when subprocess exits non-zero."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr("subprocess.run", lambda args, **kw: _make_subprocess_result("", returncode=1, stderr="auth error"))

    with pytest.raises(AgentError):
        evaluate("https://example.com", "content", ReadContext(), backend="cli")


def test_r04_cli_backend_bad_json(monkeypatch):
    """AgentError raised when subprocess returns invalid JSON."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr("subprocess.run", lambda args, **kw: _make_subprocess_result("not valid json"))

    with pytest.raises(AgentError):
        evaluate("https://example.com", "content", ReadContext(), backend="cli")


@patch("textread.agent.anthropic.Anthropic")
def test_r05_sdk_backend_unchanged(mock_cls):
    """SDK backend (default) still works unchanged."""
    client = mock_response(_VALID_JSON)
    mock_cls.return_value = client

    result = evaluate("https://example.com", "content", ReadContext(), backend="sdk")

    assert isinstance(result, Mapping)
    client.messages.create.assert_called_once()


def test_r06_parse_mapping_shared():
    """_parse_mapping returns correct Mapping for valid JSON."""
    result = _parse_mapping(_VALID_JSON)
    assert isinstance(result, Mapping)
    assert result.verdict == "worth_reading"
    assert result.score == 85


def test_r07_sanitize_strips_nulls():
    """_sanitize removes null bytes and CR characters."""
    dirty = "hello\x00world\r\nfoo"
    clean = _sanitize(dirty)
    assert "\x00" not in clean
    assert "\r" not in clean
    assert "hello" in clean
    assert "world" in clean
