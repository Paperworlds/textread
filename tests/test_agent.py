"""Tests for textread.agent (all API calls mocked)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from textread.agent import AgentError, Mapping, evaluate
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
