"""Fetch layer: pull URLs, check robots.txt, extract article text."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import warnings

import httpx
from readability import Document  # type: ignore[import-untyped]

from textread import __version__

UA = f"textread/{__version__} (+https://github.com/paperworlds/textread)"


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


def pull(url: str, refresh: bool = False, cache=None) -> FetchResult | None:
    """Fetch *url* and return a FetchResult, or None on cache hit.

    Args:
        url: The URL to fetch.
        refresh: If True, bypass the cache check.
        cache: Optional cache object with an ``exists(url) -> bool`` method.

    Raises:
        FetchBlocked: When robots.txt disallows the path.
        FetchError: On network or parse failure.
    """
    # R04: cache hit → return None
    if cache is not None and not refresh and cache.exists(url):
        return None

    try:
        # R01: robots check
        if not _robots_allowed(url):
            raise FetchBlocked(url)

        # R02/R03: download + parse via newspaper4k (imported lazily — slow to import)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            import newspaper
        config = newspaper.Config()
        config.browser_user_agent = UA
        article = newspaper.Article(url, config=config)
        article.download()
        article.parse()

        text = article.text
        final_url = article.url or url
        content_type = "text/html"

        # R07: empty text fallback via readability + raw httpx
        if not text:
            resp = httpx.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=15)
            resp.raise_for_status()
            final_url = str(resp.url)
            content_type = resp.headers.get("content-type", "text/html").split(";")[0]
            doc = Document(resp.text)
            text = _strip_tags(doc.summary())

        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return FetchResult(
            url=url,
            final_url=final_url,
            text=text,
            content_type=content_type,
            fetched_at=fetched_at,
        )

    except (FetchBlocked, FetchError):
        raise
    except Exception as exc:
        raise FetchError(str(exc)) from exc
