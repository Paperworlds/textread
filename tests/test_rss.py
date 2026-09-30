"""Tests for textread.rss — all network calls mocked."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import yaml

from textread.rss import (
    RssItem,
    _parse_items,
    _url_key,
    dedup,
    annotate_seen_before,
    canonical_url,
    digest_urls,
    fetch_feed,
    fetch_newsletter_python_weekly,
    fetch_newsletter_beehiiv_spa,
    extract_code_issue_slugs,
    parse_code_issue_meta,
    is_sponsor,
    load_seen,
    load_state,
    prune_seen,
    record_seen,
    save_seen,
    read_log,
    save_state,
    strip_utm,
    title_key,
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

def test_fetch_feed_skips_items_already_seen():
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_RSS
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_resp):
        result = fetch_feed(
            "https://feed.example.com", "devops",
            seen=[canonical_url("https://example.com/agents?utm_source=tldrdevops")],
        )

    assert [i.url for i in result.new_items] == [
        "https://sponsor.example.com/buy", "https://example.com/old",
    ]
    assert result.items_fetched == 3


def test_fetch_feed_no_state_returns_all():
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_RSS
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_resp):
        result = fetch_feed("https://feed.example.com", "devops", seen=None)

    assert len(result.new_items) == 3
    assert canonical_url("https://example.com/agents") in result.last_seen_guid


def test_fetch_feed_survives_sentinel_dropping_out_of_the_window():
    """The old single-sentinel cutoff re-emitted a whole feed once its one
    remembered item rotated out. The window must not do that."""
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_RSS
    mock_resp.raise_for_status = MagicMock()

    seen = [canonical_url(u) for u in (
        "https://vanished.example.com/rotated-out-ad",   # no longer in the feed
        "https://example.com/agents",
        "https://sponsor.example.com/buy",
        "https://example.com/old",
    )]
    with patch("httpx.get", return_value=mock_resp):
        result = fetch_feed("https://feed.example.com", "devops", seen=seen)

    assert result.new_items == []


def test_fetch_feed_window_is_bounded():
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_RSS
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_resp):
        result = fetch_feed("https://feed.example.com", "devops",
                            seen=[f"https://old.example.com/{i}" for i in range(1000)])

    assert len(result.last_seen_guid) <= 400


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def test_state_round_trip(tmp_path):
    state_file = tmp_path / "rss-state.yaml"
    state = {
        "https://feed.example.com/devops.rss": ["https://example.com/latest"],
        "https://feed.example.com/ai.rss": ["https://other.com/a", "https://other.com/b"],
    }
    save_state(state, path=state_file)
    loaded = load_state(path=state_file)
    assert loaded == state


def test_load_state_migrates_single_guid_schema(tmp_path):
    """The old schema stored one guid per feed; it must load as a one-item window."""
    state_file = tmp_path / "rss-state.yaml"
    state_file.write_text(yaml.dump({
        "https://feed.example.com/devops.rss": "https://example.com/latest?utm_source=tldr",
    }))
    assert load_state(path=state_file) == {
        "https://feed.example.com/devops.rss": ["https://example.com/latest"],
    }


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


# ---------------------------------------------------------------------------
# The Code (codenewsletter.ai) scraper
# ---------------------------------------------------------------------------

CODE_HOMEPAGE = """<html><body>
<a href="/p/older-issue">x</a>
<a href="/p/newest-issue">y</a>
<a href="/p/older-issue">duplicate</a>
<a href="/p/middle-issue">z</a>
<a href="/about">not an issue</a>
</body></html>"""


def _code_issue_html(title: str, desc: str, published: str) -> str:
    return (
        f'<html><head>'
        f'<meta property="og:title" content="{title}"/>'
        f'<meta property="og:description" content="{desc}"/>'
        f'<meta property="article:published_time" content="{published}"/>'
        f'</head><body>prose</body></html>'
    )


CODE_ISSUES = {
    "https://codenewsletter.ai/p/newest-issue": _code_issue_html(
        "Newest headline", "Also: something", "2026-09-09T13:00:00.000Z"),
    "https://codenewsletter.ai/p/middle-issue": _code_issue_html(
        "Middle headline", "Also: other", "2026-09-08T13:00:00.000Z"),
    "https://codenewsletter.ai/p/older-issue": _code_issue_html(
        "Older headline &amp; more", "Also: older", "2026-09-07T13:00:00.000Z"),
}


def _mock_code_responses():
    def _get(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = CODE_HOMEPAGE if url.endswith("/archive") else CODE_ISSUES[url]
        return resp
    return _get


def test_extract_code_issue_slugs_dedupes_and_keeps_order():
    assert extract_code_issue_slugs(CODE_HOMEPAGE) == [
        "/p/older-issue", "/p/newest-issue", "/p/middle-issue",
    ]


def test_parse_code_issue_meta_unescapes():
    meta = parse_code_issue_meta(CODE_ISSUES["https://codenewsletter.ai/p/older-issue"])
    assert meta["title"] == "Older headline & more"
    assert meta["description"] == "Also: older"
    assert meta["published_time"] == "2026-09-07T13:00:00.000Z"


def test_code_scraper_sorts_newest_first():
    with patch("httpx.get", side_effect=_mock_code_responses()):
        result = fetch_newsletter_beehiiv_spa()
    assert result.label == "code-newsletter"
    assert result.items_fetched == 3
    assert [i.title for i in result.new_items] == [
        "Newest headline", "Middle headline", "Older headline & more",
    ]
    assert result.last_seen_guid == "https://codenewsletter.ai/p/newest-issue"


def test_code_scraper_drops_issues_at_or_before_last_seen():
    with patch("httpx.get", side_effect=_mock_code_responses()):
        result = fetch_newsletter_beehiiv_spa(
            last_seen_guid="https://codenewsletter.ai/p/middle-issue"
        )
    assert [i.title for i in result.new_items] == ["Newest headline"]
    assert result.last_seen_guid == "https://codenewsletter.ai/p/newest-issue"


def test_code_scraper_skips_unreachable_issue():
    def _get(url, **kwargs):
        if url == "https://codenewsletter.ai/p/middle-issue":
            raise httpx.ConnectError("boom")
        return _mock_code_responses()(url, **kwargs)

    with patch("httpx.get", side_effect=_get):
        result = fetch_newsletter_beehiiv_spa()
    assert [i.title for i in result.new_items] == ["Newest headline", "Older headline & more"]


# ---------------------------------------------------------------------------
# canonical_url / title_key
# ---------------------------------------------------------------------------

def test_canonical_url_strips_tracking_keeps_meaning():
    assert canonical_url("https://ex.com/a?utm_source=tldr&utm_medium=x") == "https://ex.com/a"
    assert canonical_url("https://ex.com/a?id=7&utm_source=tldr") == "https://ex.com/a?id=7"
    assert canonical_url("https://EX.com/A/#frag") == "https://ex.com/A"
    assert canonical_url("https://ex.com/a?b=1&a=2") == canonical_url("https://ex.com/a?a=2&b=1")


def test_canonical_url_handles_double_escaped_entities():
    """State written by the old code carried &amp;amp; — it must still match."""
    assert canonical_url("https://ex.com/a?x=1&amp;amp;utm_source=tldr") == \
           canonical_url("https://ex.com/a?x=1&utm_source=tldr")


def test_title_key_ignores_short_titles():
    assert title_key("Projects") == ""
    assert title_key("Introducing Projects") == ""
    assert title_key("How Much Does the Harness Matter for Agents") != ""


def test_dedup_collapses_same_long_title_at_two_urls():
    items = [
        _make_item("https://harnesstax.github.io/", "devops"),
        _make_item("https://arena.ai/blog/coding-agents-harness-tax", "ai"),
    ]
    for i in items:
        i.title = "HarnessTax: How Much Does the Harness Matter for Coding Agents?"
    assert len(dedup(items)) == 1


def test_dedup_keeps_distinct_items_sharing_a_short_title():
    items = [_make_item(f"https://ex.com/{i}") for i in range(3)]
    for i in items:
        i.title = "Projects"
    assert len(dedup(items)) == 3


# ---------------------------------------------------------------------------
# Seen ledger
# ---------------------------------------------------------------------------

def test_seen_ledger_round_trip_and_first_date_wins(tmp_path):
    f = tmp_path / "rss-seen.yaml"
    seen = record_seen({}, ["https://ex.com/a?utm_source=tldr"], "2026-09-01")
    seen = record_seen(seen, ["https://ex.com/a"], "2026-09-19")
    save_seen(seen, path=f)
    assert load_seen(path=f) == {"https://ex.com/a": "2026-09-01"}


def test_prune_seen_drops_entries_past_retention():
    seen = {"https://ex.com/old": "2026-05-01", "https://ex.com/new": "2026-09-01"}
    assert prune_seen(seen, "2026-09-19", retention_days=90) == {"https://ex.com/new": "2026-09-01"}


def test_annotate_seen_before_tags_repeats_without_dropping_them():
    data = {
        "must_open": [{"url": "https://ex.com/a?utm_source=tldr", "title": "A"}],
        "groups": [{"name": "G", "items": [
            {"url": "https://ex.com/a", "title": "A"},
            {"url": "https://ex.com/fresh", "title": "B"},
        ]}],
        "save_to_raindrop": [],
    }
    tagged = annotate_seen_before(data, {"https://ex.com/a": "2026-09-14"})
    assert tagged == 2
    assert data["groups"][0]["items"][0]["seen_before"] == "2026-09-14"
    assert "seen_before" not in data["groups"][0]["items"][1]
    # nothing is removed
    assert len(data["groups"][0]["items"]) == 2


def test_digest_urls_collects_every_surface():
    data = {
        "must_open": [{"url": "https://ex.com/1"}],
        "groups": [{"name": "G", "items": [{"url": "https://ex.com/2"}]}],
        "save_to_raindrop": [{"url": "https://ex.com/3"}],
    }
    assert sorted(digest_urls(data)) == ["https://ex.com/1", "https://ex.com/2", "https://ex.com/3"]


# ---------------------------------------------------------------------------
# Dated items and the --since window
# ---------------------------------------------------------------------------

DATED_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title><![CDATA[Newest]]></title><link>https://ex.com/new</link>
  <description><![CDATA[d]]></description><guid>https://ex.com/new</guid>
  <pubDate>Tue, 29 Sep 2026 00:00:00 GMT</pubDate></item>
<item><title><![CDATA[Middle]]></title><link>https://ex.com/mid</link>
  <description><![CDATA[d]]></description><guid>https://ex.com/mid</guid>
  <pubDate>Fri, 25 Sep 2026 00:00:00 GMT</pubDate></item>
<item><title><![CDATA[Undated]]></title><link>https://ex.com/undated</link>
  <description><![CDATA[d]]></description><guid>https://ex.com/undated</guid></item>
</channel></rss>"""


def _dated_resp():
    r = MagicMock()
    r.text = DATED_RSS
    r.raise_for_status = MagicMock()
    return r


def test_parse_items_reads_pubdate():
    items = _parse_items(DATED_RSS, "https://feed", "ai")
    assert [i.published for i in items] == ["2026-09-29", "2026-09-25", None]


def test_since_filters_to_the_window():
    with patch("httpx.get", return_value=_dated_resp()):
        result = fetch_feed("https://feed", "ai", seen=None, since="2026-09-29")
    assert [i.title for i in result.new_items] == ["Newest"]


def test_since_holds_back_undated_items():
    """An undated item is not guessed at — it waits for an unbounded run."""
    with patch("httpx.get", return_value=_dated_resp()):
        result = fetch_feed("https://feed", "ai", seen=None, since="2026-01-01")
    assert [i.title for i in result.new_items] == ["Newest", "Middle"]


def test_windowed_run_leaves_the_gap_recoverable():
    """The whole point of a narrow run: items outside the window must stay
    unseen, so a later run still surfaces them."""
    with patch("httpx.get", return_value=_dated_resp()):
        narrow = fetch_feed("https://feed", "ai", seen=None, since="2026-09-29")
    assert canonical_url("https://ex.com/new") in narrow.last_seen_guid
    assert canonical_url("https://ex.com/mid") not in narrow.last_seen_guid

    with patch("httpx.get", return_value=_dated_resp()):
        catchup = fetch_feed("https://feed", "ai", seen=narrow.last_seen_guid)
    assert [i.title for i in catchup.new_items] == ["Middle", "Undated"]


def test_no_since_behaves_as_before():
    with patch("httpx.get", return_value=_dated_resp()):
        result = fetch_feed("https://feed", "ai", seen=None)
    assert len(result.new_items) == 3
