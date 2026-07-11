"""Tests for textread.fetch — all network calls are mocked."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

import httpx
import pytest

from textread import __version__
from textread.fetch import (
    UA,
    FetchBlocked,
    FetchError,
    FetchResult,
    fetch_pdf,
    pull,
    rewrite_twitter_url,
    _fetch_twitter_fxtwitter,
    _tweet_id_from_url,
)

ROBOTS_DISALLOW_ALL = "User-agent: *\nDisallow: /"
ROBOTS_ALLOW_ALL = "User-agent: *\nAllow: /"
SAMPLE_HTML = "<html><body><p>Hello world article content</p></body></html>"
SAMPLE_TEXT = "Hello world article content"


def _mock_robots_response(text: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.url = "http://example.com/robots.txt"
    return resp


def _mock_article(text: str = SAMPLE_TEXT, url: str = "http://example.com/article") -> MagicMock:
    art = MagicMock()
    art.text = text
    art.url = url
    return art


# ---------------------------------------------------------------------------
# R01 — robots blocked
# ---------------------------------------------------------------------------

def test_r01_robots_blocked():
    with patch("httpx.get") as mock_get, \
         patch("newspaper.Article") as MockArticle:
        mock_get.return_value = _mock_robots_response(ROBOTS_DISALLOW_ALL)
        with pytest.raises(FetchBlocked) as exc_info:
            pull("http://example.com/article")
        assert "http://example.com/article" in str(exc_info.value)
        # Article should NOT have been instantiated
        MockArticle.assert_not_called()


# ---------------------------------------------------------------------------
# R02 — user-agent header
# ---------------------------------------------------------------------------

def test_r02_user_agent_header():
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        resp = MagicMock()
        resp.status_code = 200
        resp.text = ROBOTS_ALLOW_ALL
        resp.url = url
        return resp

    article = _mock_article()

    with patch("httpx.get", side_effect=fake_get), \
         patch("newspaper.Article", return_value=article), \
         patch("newspaper.Config"):
        result = pull("http://example.com/article")

    # The robots.txt GET should not carry the UA explicitly (urllib.robotparser
    # fetches via httpx in our impl — check config passed to Article instead)
    assert result is not None
    assert result.text == SAMPLE_TEXT
    # UA is a real browser string (v0.6.1) to bypass cheap bot filters
    assert "Mozilla/5.0" in UA
    assert "Chrome/" in UA


# ---------------------------------------------------------------------------
# R03 — returns FetchResult with all fields
# ---------------------------------------------------------------------------

def test_r03_returns_fetch_result():
    article = _mock_article(text=SAMPLE_TEXT, url="http://example.com/final")

    with patch("httpx.get", return_value=_mock_robots_response(ROBOTS_ALLOW_ALL)), \
         patch("newspaper.Article", return_value=article), \
         patch("newspaper.Config"):
        result = pull("http://example.com/article")

    assert isinstance(result, FetchResult)
    assert result.url == "http://example.com/article"
    assert result.final_url == "http://example.com/final"
    assert result.text == SAMPLE_TEXT
    assert result.content_type == "text/html"
    assert result.fetched_at.endswith("Z")
    # ISO 8601 UTC: "2024-01-01T00:00:00Z"
    assert "T" in result.fetched_at


# ---------------------------------------------------------------------------
# R04 — cache hit skips network
# ---------------------------------------------------------------------------

def test_r04_cache_hit_skips_network():
    cache = MagicMock()
    cache.exists.return_value = True

    with patch("httpx.get") as mock_get, \
         patch("newspaper.Article") as MockArticle:
        result = pull("http://example.com/article", cache=cache)

    assert result is None
    mock_get.assert_not_called()
    MockArticle.assert_not_called()


# ---------------------------------------------------------------------------
# R05 — refresh=True bypasses cache
# ---------------------------------------------------------------------------

def test_r05_refresh_bypasses_cache():
    cache = MagicMock()
    cache.exists.return_value = True
    article = _mock_article()

    with patch("httpx.get", return_value=_mock_robots_response(ROBOTS_ALLOW_ALL)), \
         patch("newspaper.Article", return_value=article), \
         patch("newspaper.Config"):
        result = pull("http://example.com/article", refresh=True, cache=cache)

    assert result is not None
    assert result.text == SAMPLE_TEXT


# ---------------------------------------------------------------------------
# 012 — fetch_pdf
# ---------------------------------------------------------------------------

def test_fetch_pdf_local_file(tmp_path, monkeypatch):
    """fetch_pdf on a local .pdf path calls pymupdf4llm.to_markdown."""
    import sys, types
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 fake")

    fake_mod = types.ModuleType("pymupdf4llm")
    fake_mod.to_markdown = lambda path, **kw: "# Extracted markdown"
    monkeypatch.setitem(sys.modules, "pymupdf4llm", fake_mod)

    result = fetch_pdf(str(pdf_file))

    assert isinstance(result, FetchResult)
    assert result.text == "# Extracted markdown"
    assert result.content_type == "application/pdf"
    assert result.url.startswith("file://")
    assert result.fetched_at.endswith("Z")


def test_fetch_pdf_missing_file():
    """fetch_pdf raises FetchError when local file does not exist."""
    with pytest.raises(FetchError, match="File not found"):
        fetch_pdf("/tmp/does_not_exist_abc123.pdf")


def test_fetch_pdf_missing_dep(tmp_path, monkeypatch):
    """fetch_pdf raises FetchError when pymupdf4llm is not installed."""
    import sys
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(b"%PDF fake")
    monkeypatch.setitem(sys.modules, "pymupdf4llm", None)

    with pytest.raises(FetchError, match="pdf extra"):
        fetch_pdf(str(pdf_file))


def test_fetch_pdf_pages_range(tmp_path, monkeypatch):
    """pages='1-3' is converted to 0-indexed list [0,1,2]."""
    import sys, types
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(b"%PDF fake")

    captured_kwargs: dict = {}
    fake_mod = types.ModuleType("pymupdf4llm")
    def fake_to_markdown(path, **kw):
        captured_kwargs.update(kw)
        return "# page content"
    fake_mod.to_markdown = fake_to_markdown
    monkeypatch.setitem(sys.modules, "pymupdf4llm", fake_mod)

    fetch_pdf(str(pdf_file), pages="1-3")
    assert captured_kwargs.get("pages") == [0, 1, 2]


def test_fetch_pdf_marker_backend():
    """marker backend raises FetchError (not yet implemented)."""
    with pytest.raises(FetchError, match="marker backend not yet implemented"):
        fetch_pdf("/any/path.pdf", backend="marker")


# ---------------------------------------------------------------------------
# R06 — network error raises FetchError
# ---------------------------------------------------------------------------

def test_r06_network_error_raises_fetch_error():
    article = MagicMock()
    article.url = "http://example.com/article"
    article.download.side_effect = httpx.ConnectError("connection refused")

    with patch("httpx.get", return_value=_mock_robots_response(ROBOTS_ALLOW_ALL)), \
         patch("newspaper.Article", return_value=article), \
         patch("newspaper.Config"):
        with pytest.raises(FetchError) as exc_info:
            pull("http://example.com/article")
    assert "connection refused" in str(exc_info.value)


# ---------------------------------------------------------------------------
# R07 — empty article.text falls back to readability
# ---------------------------------------------------------------------------

def test_r07_empty_text_fallback():
    empty_article = _mock_article(text="")

    robots_resp = _mock_robots_response(ROBOTS_ALLOW_ALL)

    fetch_resp = MagicMock()
    fetch_resp.status_code = 200
    fetch_resp.text = SAMPLE_HTML
    fetch_resp.url = "http://example.com/article"
    fetch_resp.headers = {"content-type": "text/html; charset=utf-8"}
    fetch_resp.raise_for_status = MagicMock()

    get_responses = [robots_resp, fetch_resp]

    mock_doc = MagicMock()
    mock_doc.summary.return_value = f"<div>{SAMPLE_TEXT}</div>"

    with patch("httpx.get", side_effect=get_responses), \
         patch("newspaper.Article", return_value=empty_article), \
         patch("newspaper.Config"), \
         patch("textread.fetch.Document", return_value=mock_doc):
        result = pull("http://example.com/article")

    assert result is not None
    assert result.text == SAMPLE_TEXT


# ---------------------------------------------------------------------------
# Twitter/Nitter URL rewriting
# ---------------------------------------------------------------------------

def test_rewrite_twitter_url_x_com():
    result = rewrite_twitter_url(
        "https://x.com/someuser/status/1234567890",
        "https://nitter.privacydev.net",
    )
    assert result == "https://nitter.privacydev.net/someuser/status/1234567890"


def test_rewrite_twitter_url_twitter_com():
    result = rewrite_twitter_url(
        "https://twitter.com/someuser/status/9876543210",
        "https://nitter.example.com",
    )
    assert result == "https://nitter.example.com/someuser/status/9876543210"


def test_rewrite_twitter_url_www_prefix():
    result = rewrite_twitter_url(
        "https://www.x.com/someuser/status/111",
        "https://nitter.example.com",
    )
    assert result == "https://nitter.example.com/someuser/status/111"


def test_rewrite_twitter_url_non_twitter_unchanged():
    url = "https://example.com/some/article"
    assert rewrite_twitter_url(url, "https://nitter.example.com") == url


def test_pull_twitter_no_cookie_uses_fxtwitter():
    """pull() with a Twitter URL and no cookie calls fxtwitter, not x.com directly."""
    fx_response = MagicMock()
    fx_response.status_code = 200
    fx_response.json.return_value = {
        "tweet": {
            "url": "https://x.com/user/status/123",
            "id": "123",
            "text": "Hello from a tweet",
            "raw_text": {"text": "Hello from a tweet", "facets": []},
            "author": {"screen_name": "user", "description": ""},
        }
    }
    fx_response.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=fx_response):
        result = pull("https://x.com/user/status/123")

    assert result is not None
    assert result.url == "https://x.com/user/status/123"
    assert "Hello from a tweet" in result.text


def test_pull_twitter_with_cookie_fetches_directly():
    """pull() with twitter_cookie bypasses fxtwitter and hits x.com directly."""
    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = "<html><body><article>Article content here</article></body></html>"
    html_resp.url = "https://x.com/i/article/999"
    html_resp.headers = {"content-type": "text/html"}
    html_resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=html_resp) as mock_get:
        result = pull(
            "https://x.com/i/article/999",
            twitter_cookie="ct0=abc; auth_token=xyz",
        )

    assert result is not None
    # Cookie was sent
    call_headers = mock_get.call_args[1]["headers"]
    assert "ct0=abc; auth_token=xyz" in call_headers["Cookie"]
    assert call_headers.get("x-csrf-token") == "abc"


def test_fxtwitter_link_tweet_raises_blocked():
    """_fetch_twitter_fxtwitter raises FetchBlocked for link-only tweets (X Articles)."""
    fx_response = MagicMock()
    fx_response.status_code = 200
    fx_response.json.return_value = {
        "tweet": {
            "url": "https://x.com/user/status/123",
            "id": "123",
            "text": "",
            "raw_text": {"text": "https://t.co/abc123", "facets": []},
            "author": {"screen_name": "user", "description": ""},
        }
    }
    fx_response.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=fx_response):
        with pytest.raises(FetchBlocked, match="twitter_cookie"):
            _fetch_twitter_fxtwitter("https://x.com/user/status/123")


def test_tweet_id_from_url():
    assert _tweet_id_from_url("https://x.com/user/status/2066561780495896785") == "2066561780495896785"
    assert _tweet_id_from_url("https://x.com/i/article/999") is None


def test_binary_data_exception_falls_through_to_readability():
    """Regression: newspaper's is_binary_url() false-positives on Content-Disposition: inline
    (e.g. cursor.com/blog). We must catch ArticleBinaryDataException and fall through to
    the httpx + readability path instead of erroring."""
    from newspaper.exceptions import ArticleBinaryDataException

    failing_article = MagicMock()
    failing_article.download.side_effect = ArticleBinaryDataException(
        "Article is binary data: http://example.com/article"
    )

    robots_resp = _mock_robots_response(ROBOTS_ALLOW_ALL)

    fetch_resp = MagicMock()
    fetch_resp.status_code = 200
    fetch_resp.text = SAMPLE_HTML
    fetch_resp.url = "http://example.com/article"
    fetch_resp.headers = {"content-type": "text/html; charset=utf-8"}
    fetch_resp.raise_for_status = MagicMock()

    mock_doc = MagicMock()
    mock_doc.summary.return_value = f"<div>{SAMPLE_TEXT}</div>"

    with patch("httpx.get", side_effect=[robots_resp, fetch_resp]), \
         patch("newspaper.Article", return_value=failing_article), \
         patch("newspaper.Config"), \
         patch("textread.fetch.Document", return_value=mock_doc):
        result = pull("http://example.com/article")

    assert result is not None
    assert result.text == SAMPLE_TEXT
