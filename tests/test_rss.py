"""Tests for textread.rss — all network calls mocked."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from textread.rss import (
    RssItem,
    _parse_items,
    _url_key,
    dedup,
    fetch_feed,
    fetch_newsletter_python_weekly,
    is_sponsor,
    load_state,
    read_log,
    save_state,
    strip_utm,
    update_save_status,
    write_log,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0">
<channel>
<item>
  <title><![CDATA[Great Article About Agents]]></title>
  <link>https://example.com/agents?utm_source=tldrdevops&utm_medium=newsletter</link>
  <description><![CDATA[A deep dive into agent infrastructure patterns.]]></description>
  <guid>https://example.com/agents?utm_source=tldrdevops</guid>
</item>
<item>
  <title><![CDATA[Buy our product now (Sponsor)]]></title>
  <link>https://sponsor.example.com/buy</link>
  <description><![CDATA[We sell things.]]></description>
  <guid>https://sponsor.example.com/buy</guid>
</item>
<item>
  <title><![CDATA[Old Article]]></title>
  <link>https://example.com/old</link>
  <description><![CDATA[Something old.]]></description>
  <guid>https://example.com/old</guid>
</item>
</channel>
</rss>"""


def _make_item(url: str = "https://example.com/article", label: str = "devops") -> RssItem:
    return RssItem(title="Title", url=url, description="Desc", guid=url,
                   source_feed="https://feed.example.com", label=label)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def test_parse_items_basic():
    items = _parse_items(SAMPLE_RSS, "https://feed.example.com", "devops")
    assert len(items) == 3
    assert items[0].title == "Great Article About Agents"
    # _unescape converts &amp; → & so URL is parseable, UTM params preserved until strip_utm()
    assert "utm_source=tldrdevops" in items[0].url
    assert items[1].title == "Buy our product now (Sponsor)"
    assert items[2].guid == "https://example.com/old"


def test_parse_items_label_set():
    items = _parse_items(SAMPLE_RSS, "https://feed.example.com", "ai")
    assert all(i.label == "ai" for i in items)


# ---------------------------------------------------------------------------
# Sponsor filter
# ---------------------------------------------------------------------------

def test_is_sponsor_true():
    item = _make_item()
    item.title = "Buy this now (Sponsor)"
    assert is_sponsor(item) is True


def test_is_sponsor_false():
    item = _make_item()
    item.title = "Great technical article"
    assert is_sponsor(item) is False


def test_is_sponsor_case_insensitive():
    item = _make_item()
    item.title = "SOMETHING (SPONSOR)"
    assert is_sponsor(item) is True


# ---------------------------------------------------------------------------
# UTM stripping
# ---------------------------------------------------------------------------

def test_strip_utm_removes_utm_params():
    url = "https://example.com/article?utm_source=tldr&utm_medium=newsletter"
    assert strip_utm(url) == "https://example.com/article"


def test_strip_utm_keeps_non_utm_params():
    url = "https://example.com/article?page=2&utm_source=tldr"
    assert strip_utm(url) == "https://example.com/article?page=2"


def test_strip_utm_no_query():
    url = "https://example.com/article"
    assert strip_utm(url) == url


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def test_dedup_removes_cross_feed_duplicates():
    items = [
        _make_item("https://example.com/article?utm_source=tldrdevops", "devops"),
        _make_item("https://example.com/article?utm_source=tldrai", "ai"),
        _make_item("https://other.com/post", "tech"),
    ]
    result = dedup(items)
    assert len(result) == 2
    assert result[0].label == "devops"  # first occurrence kept


def test_dedup_preserves_unique_items():
    items = [_make_item(f"https://example.com/{i}") for i in range(4)]
    assert len(dedup(items)) == 4


# ---------------------------------------------------------------------------
# fetch_feed — new items since last_seen_guid
# ---------------------------------------------------------------------------

def test_fetch_feed_new_items_only():
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_RSS
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_resp):
        result = fetch_feed(
            "https://feed.example.com", "devops",
            last_seen_guid="https://example.com/agents?utm_source=tldrdevops",
        )

    # last_seen_guid is the first item — nothing newer
    assert result.new_items == []
    assert result.items_fetched == 3


def test_fetch_feed_no_last_guid_returns_all():
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_RSS
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_resp):
        result = fetch_feed("https://feed.example.com", "devops", last_seen_guid=None)

    assert len(result.new_items) == 3
    assert result.last_seen_guid == "https://example.com/agents?utm_source=tldrdevops"


def test_fetch_feed_partial_new():
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_RSS
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_resp):
        result = fetch_feed(
            "https://feed.example.com", "devops",
            last_seen_guid="https://example.com/old",
        )

    # old is 3rd item — 2 items are newer
    assert len(result.new_items) == 2


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def test_state_round_trip(tmp_path):
    state_file = tmp_path / "rss-state.yaml"
    state = {
        "https://feed.example.com/devops.rss": "https://example.com/latest",
        "https://feed.example.com/ai.rss": "https://other.com/article",
    }
    save_state(state, path=state_file)
    loaded = load_state(path=state_file)
    assert loaded == state


def test_load_state_missing_file(tmp_path):
    assert load_state(path=tmp_path / "nonexistent.yaml") == {}


# ---------------------------------------------------------------------------
# Log read/write/update
# ---------------------------------------------------------------------------

def test_write_and_read_log(tmp_path):
    data = {
        "date": "2026-06-17",
        "must_open": [{"url": "https://example.com", "title": "T", "source": "devops", "reason": "r"}],
        "save_to_raindrop": [{"url": "https://example.com", "title": "T", "source": "devops", "status": "pending"}],
    }
    write_log(data, "2026-06-17", digests_dir=tmp_path)
    loaded = read_log("2026-06-17", digests_dir=tmp_path)
    assert loaded["date"] == "2026-06-17"
    assert loaded["save_to_raindrop"][0]["status"] == "pending"


def test_read_log_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_log("2026-01-01", digests_dir=tmp_path)


def test_update_save_status(tmp_path):
    data = {
        "date": "2026-06-17",
        "save_to_raindrop": [
            {"url": "https://a.com", "title": "A", "status": "pending"},
            {"url": "https://b.com", "title": "B", "status": "pending"},
        ],
    }
    write_log(data, "2026-06-17", digests_dir=tmp_path)
    update_save_status("2026-06-17", "https://a.com", "added", digests_dir=tmp_path)
    loaded = read_log("2026-06-17", digests_dir=tmp_path)
    statuses = {e["url"]: e["status"] for e in loaded["save_to_raindrop"]}
    assert statuses["https://a.com"] == "added"
    assert statuses["https://b.com"] == "pending"


# ---------------------------------------------------------------------------
# Python Weekly newsletter scraper
# ---------------------------------------------------------------------------

_PW_HOMEPAGE_HTML = """
<html><body>
<a href="/p/python-weekly-issue-750-june-18-2026">Issue 750</a>
</body></html>
"""

_PW_ISSUE_HTML = """
<html><body>
<h6 style="color:#1173c7"><a class="link" href="https://article1.com/post?utm_source=www.pythonweekly.com&amp;utm_medium=newsletter">First Article Title</a></h6>
<div><style>p span { line-height: 1.6; }</style><div><p style="color:#2D2D2D;">Description of first article here.</p></div></div>
<h6 style="color:#1173c7"><a class="link" href="https://article2.com/page?utm_source=www.pythonweekly.com&amp;utm_medium=newsletter">Second Article Title</a></h6>
<div><style>p span { line-height: 1.6; }</style><div><p style="color:#2D2D2D;">Description of second article here.</p></div></div>
</body></html>
"""


def _mock_pw_responses(issue_url=None):
    """Return a side_effect list for httpx.get calls."""
    homepage_resp = MagicMock()
    homepage_resp.text = _PW_HOMEPAGE_HTML
    homepage_resp.raise_for_status = MagicMock()

    issue_resp = MagicMock()
    issue_resp.text = _PW_ISSUE_HTML
    issue_resp.raise_for_status = MagicMock()

    if issue_url:
        return [issue_resp]
    return [homepage_resp, issue_resp]


def test_pw_scraper_auto_detect_latest():
    with patch("httpx.get", side_effect=_mock_pw_responses()):
        result = fetch_newsletter_python_weekly(cookie="test-cookie")
    assert "python-weekly-issue-750" in result.url
    assert result.items_fetched == 2
    assert result.new_items[0].title == "First Article Title"
    assert result.new_items[1].title == "Second Article Title"
    assert result.last_seen_guid == result.url


def test_pw_scraper_explicit_issue_url():
    issue_url = "https://www.pythonweekly.com/p/python-weekly-issue-750-june-18-2026"
    with patch("httpx.get", side_effect=_mock_pw_responses(issue_url=issue_url)):
        result = fetch_newsletter_python_weekly(cookie="test-cookie", issue_url=issue_url)
    assert result.items_fetched == 2
    assert result.label == "python-weekly"


def test_pw_scraper_already_seen_skips():
    issue_url = "https://www.pythonweekly.com/p/python-weekly-issue-750-june-18-2026"
    with patch("httpx.get", side_effect=_mock_pw_responses(issue_url=issue_url)):
        result = fetch_newsletter_python_weekly(
            cookie="test-cookie", issue_url=issue_url, last_seen_guid=issue_url
        )
    assert result.new_items == []
    assert result.items_fetched == 0


def test_pw_scraper_strips_html_from_titles():
    html_with_bold = _PW_ISSUE_HTML.replace(
        "First Article Title",
        "First <b>Article</b> Title",
    )
    issue_url = "https://www.pythonweekly.com/p/issue"
    resp = MagicMock()
    resp.text = html_with_bold
    resp.raise_for_status = MagicMock()
    with patch("httpx.get", return_value=resp):
        result = fetch_newsletter_python_weekly(cookie="test-cookie", issue_url=issue_url)
    assert result.new_items[0].title == "First Article Title"


def test_pw_scraper_guid_is_utm_stripped():
    issue_url = "https://www.pythonweekly.com/p/issue"
    resp = MagicMock()
    resp.text = _PW_ISSUE_HTML
    resp.raise_for_status = MagicMock()
    with patch("httpx.get", return_value=resp):
        result = fetch_newsletter_python_weekly(cookie="test-cookie", issue_url=issue_url)
    # guid should have no utm params
    assert "utm_source" not in result.new_items[0].guid
    # but url still carries them (stripped at save time)
    assert "utm_source=www.pythonweekly.com" in result.new_items[0].url
