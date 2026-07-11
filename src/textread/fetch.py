"""Fetch layer: pull URLs, check robots.txt, extract article text."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

_TWITTER_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
_FXTWITTER_API = "https://api.fxtwitter.com/status/{tweet_id}"

import warnings

import httpx
from readability import Document  # type: ignore[import-untyped]

from textread import __version__

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class FetchResult:
    url: str
    final_url: str
    text: str
    content_type: str
    fetched_at: str


class FetchBlocked(Exception):
    """Raised when robots.txt disallows the URL."""


class FetchError(Exception):
    """Raised on network failure or unrecoverable parse error."""


def _is_twitter_url(url: str) -> bool:
    return urlparse(url).netloc in _TWITTER_HOSTS


def _tweet_id_from_url(url: str) -> str | None:
    """Extract the numeric tweet/status ID from an x.com or twitter.com status URL."""
    m = re.search(r"/status/(\d+)", url)
    return m.group(1) if m else None


def rewrite_twitter_url(url: str, nitter_instance: str) -> str:
    """Rewrite x.com/twitter.com URLs to a Nitter instance URL.

    Preserves the path (/<user>/status/<id>, /i/web/status/<id>, etc.).
    Non-Twitter URLs are returned unchanged.
    """
    parsed = urlparse(url)
    if parsed.netloc not in _TWITTER_HOSTS:
        return url
    nitter = nitter_instance.rstrip("/")
    return f"{nitter}{parsed.path}"


def _fetch_twitter_cookie(url: str, cookie: str) -> FetchResult:
    """Fetch a Twitter/X URL directly using a browser session cookie.

    Bypasses robots.txt — the cookie represents an authenticated user who
    has agreed to X's ToS and is allowed to access this content.
    """
    # Extract ct0 for the CSRF header (required by X for authenticated fetches)
    csrf = ""
    for part in cookie.split(";"):
        k, _, v = part.strip().partition("=")
        if k.strip() == "ct0":
            csrf = v.strip()
            break

    headers = {
        "User-Agent": UA,
        "Cookie": cookie,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if csrf:
        headers["x-csrf-token"] = csrf

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=15)
        resp.raise_for_status()
        final_url = str(resp.url)
        content_type = resp.headers.get("content-type", "text/html").split(";")[0]
        doc = Document(resp.text)
        text = _strip_tags(doc.summary())
        return FetchResult(url=url, final_url=final_url, text=text,
                           content_type=content_type, fetched_at=fetched_at)
    except Exception as exc:
        raise FetchError(str(exc)) from exc


def _fetch_twitter_fxtwitter(url: str) -> FetchResult:
    """Fetch tweet content via the fxtwitter API (no auth, tweet status URLs only).

    Works for tweets with text. For link-only tweets that point to X Articles,
    raises FetchBlocked since articles require authentication.
    """
    tweet_id = _tweet_id_from_url(url)
    if not tweet_id:
        raise FetchBlocked(url)

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        resp = httpx.get(
            _FXTWITTER_API.format(tweet_id=tweet_id),
            headers={"User-Agent": UA},
            follow_redirects=True,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise FetchError(str(exc)) from exc

    tweet = data.get("tweet", {})
    if not tweet:
        raise FetchBlocked(url)

    text = tweet.get("text", "").strip()
    author = tweet.get("author", {}).get("screen_name", "")
    author_desc = tweet.get("author", {}).get("description", "")

    # Link-only tweet: raw_text is just a t.co URL → article likely requires auth
    raw_text = tweet.get("raw_text", {}).get("text", "").strip()
    if not text and raw_text.startswith("https://t.co"):
        raise FetchBlocked(
            f"{url} — link tweet pointing to X Article; set twitter_cookie in config to read"
        )

    if not text:
        raise FetchBlocked(url)

    full_text = f"@{author}\n\n{text}"
    if author_desc:
        full_text += f"\n\n---\n{author_desc}"

    return FetchResult(
        url=url,
        final_url=url,
        text=full_text,
        content_type="text/plain",
        fetched_at=fetched_at,
    )


def _robots_allowed(url: str) -> bool:
    """Return True if our UA is allowed to fetch *url*, False if disallowed.

    Any error fetching robots.txt is treated as allow-all.
    """
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        resp = httpx.get(robots_url, follow_redirects=True, timeout=10)
        rp = RobotFileParser()
        rp.set_url(robots_url)
        if resp.status_code == 200:
            rp.parse(resp.text.splitlines())
        else:
            return True  # no robots.txt → allow all
        return rp.can_fetch(UA, url)
    except Exception:
        return True  # network error → allow all


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html).strip()


def pull(
    url: str,
    refresh: bool = False,
    cache=None,
    nitter_instance: str = "https://nitter.privacydev.net",
    twitter_cookie: str | None = None,
) -> FetchResult | None:
    """Fetch *url* and return a FetchResult, or None on cache hit.

    Twitter/X URL resolution order:
      1. If twitter_cookie is set: fetch directly with session cookie (handles
         tweets, threads, and X Articles).
      2. Else if URL contains /status/<id>: try fxtwitter API (no auth, tweets only).
      3. Else: raise FetchBlocked (X Articles require auth).

    Args:
        url: The URL to fetch.
        refresh: If True, bypass the cache check.
        cache: Optional cache object with an ``exists(url) -> bool`` method.
        nitter_instance: Kept for backwards compatibility; unused when twitter_cookie is set.
        twitter_cookie: Raw Cookie header value from a logged-in X browser session,
            e.g. ``"ct0=abc123; auth_token=xyz789"``.

    Raises:
        FetchBlocked: When robots.txt disallows the URL, or Twitter content
            requires auth and no cookie is configured.
        FetchError: On network or parse failure.
    """
    import time
    try:
        from textread import traces as _traces
    except Exception:
        _traces = None  # type: ignore[assignment]

    # R04: cache hit → return None (keyed on original URL)
    if cache is not None and not refresh and cache.exists(url):
        if _traces:
            try:
                _traces.record(tool="textread", operation="fetch",
                               ref=url, latency_ms=0, cache_hit=True)
            except Exception:
                pass
        return None

    # Twitter/X path — bypass normal robots check
    if _is_twitter_url(url):
        t0 = time.monotonic()
        try:
            if twitter_cookie:
                result = _fetch_twitter_cookie(url, twitter_cookie)
            else:
                result = _fetch_twitter_fxtwitter(url)
        except (FetchBlocked, FetchError) as exc:
            if _traces:
                try:
                    _traces.record(tool="textread", operation="fetch", ref=url,
                                   latency_ms=int((time.monotonic() - t0) * 1000),
                                   cache_hit=False, blocked=True, reason=str(exc))
                except Exception:
                    pass
            raise
        if _traces:
            try:
                _traces.record(tool="textread", operation="fetch", ref=url,
                               latency_ms=int((time.monotonic() - t0) * 1000),
                               cache_hit=False, content_type=result.content_type)
            except Exception:
                pass
        return result

    fetch_url = url
    t0 = time.monotonic()

    try:
        # R01: robots check
        if not _robots_allowed(fetch_url):
            raise FetchBlocked(url)

        # R02/R03: download + parse via newspaper4k (imported lazily — slow to import)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            import newspaper
            from newspaper.exceptions import ArticleBinaryDataException
        config = newspaper.Config()
        config.browser_user_agent = UA
        article = newspaper.Article(fetch_url, config=config)
        try:
            article.download()
            article.parse()
            text = article.text
            final_url = article.url or fetch_url
        except ArticleBinaryDataException:
            # newspaper's binary check false-positives on Content-Disposition: inline.
            # Fall through to the readability path, which doesn't run that check.
            text = ""
            final_url = fetch_url
        content_type = "text/html"

        # R07: empty text fallback via readability + raw httpx
        if not text:
            resp = httpx.get(fetch_url, headers={"User-Agent": UA}, follow_redirects=True, timeout=15)
            resp.raise_for_status()
            final_url = str(resp.url)
            content_type = resp.headers.get("content-type", "text/html").split(";")[0]
            doc = Document(resp.text)
            text = _strip_tags(doc.summary())

        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = FetchResult(
            url=url,
            final_url=final_url,
            text=text,
            content_type=content_type,
            fetched_at=fetched_at,
        )
        if _traces:
            try:
                _traces.record(
                    tool="textread", operation="fetch", ref=url,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    cache_hit=False, content_type=content_type,
                    content_len=len(text),
                )
            except Exception:
                pass
        return result

    except (FetchBlocked, FetchError) as exc:
        if _traces:
            try:
                _traces.record(
                    tool="textread", operation="fetch", ref=url,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    cache_hit=False, blocked=isinstance(exc, FetchBlocked),
                    reason=str(exc),
                )
            except Exception:
                pass
        raise
    except Exception as exc:
        raise FetchError(str(exc)) from exc


def fetch_pdf(source: str, pages: str | None = None, backend: str = "native") -> FetchResult:
    """Extract text from a PDF (local path or remote URL) as markdown.

    Args:
        source: Local file path or http(s) URL pointing to a PDF.
        pages: Optional page range, e.g. "1-5" or "3".
        backend: Extraction backend — "native" (pymupdf4llm) or "marker" (planned).

    Raises:
        FetchError: On missing dependency, missing file, download failure, or extraction error.
    """
    if backend == "marker":
        raise FetchError("marker backend not yet implemented — use --backend native")

    if source.startswith(("http://", "https://")):
        try:
            resp = httpx.get(source, headers={"User-Agent": UA}, follow_redirects=True, timeout=30)
            resp.raise_for_status()
        except Exception as exc:
            raise FetchError(str(exc)) from exc
        import os, tempfile
        fd, tmp_name = tempfile.mkstemp(suffix=".pdf")
        try:
            os.write(fd, resp.content)
            os.close(fd)
            return _extract_pdf(source, Path(tmp_name), pages)
        finally:
            Path(tmp_name).unlink(missing_ok=True)
    else:
        local = Path(source).expanduser().resolve()
        if not local.exists():
            raise FetchError(f"File not found: {source}")
        return _extract_pdf(local.as_uri(), local, pages)


def _extract_pdf(url: str, path: Path, pages: str | None) -> FetchResult:
    try:
        import pymupdf4llm  # type: ignore[import]
    except ImportError:
        raise FetchError("PDF support requires the pdf extra — run: uv sync --extra pdf")

    kwargs: dict = {}
    if pages:
        start, _, end = pages.partition("-")
        kwargs["pages"] = list(range(int(start) - 1, int(end))) if end else [int(start) - 1]

    try:
        text = pymupdf4llm.to_markdown(str(path), **kwargs)
    except Exception as exc:
        raise FetchError(f"PDF extraction failed: {exc}") from exc

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return FetchResult(url=url, final_url=url, text=text, content_type="application/pdf", fetched_at=fetched_at)
