---
id: '003'
title: Fetch layer
repo: textread
model: sonnet
budget_usd: 1.50
phase: textread
depends_on: ['001', '004']
---

# 003 — Fetch layer

## Requirements

- R01: WHEN `fetch.pull(url)` is called and the robots.txt for that domain disallows
  the path, THE SYSTEM SHALL raise `FetchBlocked` with a message naming the URL.
- R02: WHEN `fetch.pull(url)` is called with a reachable URL, THE SYSTEM SHALL set
  the `User-Agent` header to `textread/<version> (+https://github.com/paperworlds/textread)`.
- R03: WHEN `fetch.pull(url)` succeeds, THE SYSTEM SHALL return a `FetchResult`
  containing `text` (extracted article text), `content_type`, `final_url`, and
  `fetched_at` (ISO 8601 UTC).
- R04: WHEN `fetch.pull(url)` is called and the URL is already in the cache,
  THE SYSTEM SHALL return `None` without making a network request (cache-hit path).
- R05: WHEN `fetch.pull(url, refresh=True)` is called, THE SYSTEM SHALL bypass the
  cache check and always fetch from the network.
- R06: WHEN a network error occurs during fetch, THE SYSTEM SHALL raise `FetchError`
  with the underlying exception message.
- R07: WHEN newspaper4k returns an empty `text` field, THE SYSTEM SHALL fall back to
  `readability-lxml` + raw httpx GET for body extraction.

## Design

### overview

`fetch.py` is a thin wrapper around newspaper4k. It owns only the network concern —
it does not write to the cache (that is cache.py's job). The caller (cli.py) receives
a `FetchResult | None` and decides whether to write. Robots.txt is checked via stdlib
`urllib.robotparser` before any real HTTP request is made. newspaper4k is invoked via
`newspaper.Article` — parse-only mode, no download threading.

### modules

- `src/textread/fetch.py` — New file. `FetchResult`, `FetchBlocked`, `FetchError`,
  `pull(url, refresh=False, cache=None) -> FetchResult | None`.
- `tests/test_fetch.py` — New file. All tests mock httpx and newspaper4k; no network.

### data_structures

```python
@dataclass
class FetchResult:
    url: str               # original URL as passed
    final_url: str         # after redirects
    text: str              # extracted article text
    content_type: str      # e.g. "text/html"
    fetched_at: str        # ISO 8601 UTC

class FetchBlocked(Exception):
    """Raised when robots.txt disallows the URL."""

class FetchError(Exception):
    """Raised on network failure or unrecoverable parse error."""
```

### sequence

pull_flow:
  1. If `cache` is not None and `cache.exists(url)` and not `refresh` → return None (R04).
  2. Parse domain from `url`. Fetch `{scheme}://{domain}/robots.txt` via httpx (silent
     on 404 — treat as allow-all). Parse with `urllib.robotparser.RobotFileParser`.
     If disallowed for our UA → raise `FetchBlocked(url)` (R01).
  3. Build `newspaper.Article(url)`. Set `config.browser_user_agent` to our UA string (R02).
     Call `article.download()` then `article.parse()`.
  4. If `article.text` is empty → fall back: raw httpx GET, pass HTML to
     `readability.Document(html).summary()`, strip tags (R07).
  5. Return `FetchResult(url=url, final_url=..., text=..., content_type=...,
     fetched_at=datetime.utcnow().isoformat() + "Z")` (R03).
  6. Wrap all network operations in try/except; re-raise as `FetchError` (R06).

### degradation

All exceptions from httpx and newspaper4k are caught and re-raised as `FetchError`.
robots.txt fetch failure (network error on robots endpoint) is treated as allow-all
to avoid blocking legitimate reads.

## Steps

1. Add `readability-lxml` to `pyproject.toml` dependencies.

2. Create `src/textread/fetch.py`:
   - `FetchResult`, `FetchBlocked`, `FetchError` per `data_structures`.
   - `_robots_allowed(url: str) -> bool` — internal helper: fetch robots.txt, parse,
     check our UA. Returns True on any fetch error (allow-all fallback).
   - `pull(url: str, refresh: bool = False, cache=None) -> FetchResult | None`
     per `sequence.pull_flow`.
   - Import `__version__` from `textread` to build the UA string.

3. Create `tests/test_fetch.py`:
   - `test_r01_robots_blocked` — mock httpx to return a robots.txt that disallows `/`;
     assert `FetchBlocked` is raised.
   - `test_r02_user_agent_header` — capture the httpx request; assert UA header matches
     the expected string.
   - `test_r03_returns_fetch_result` — mock Article.download/parse returning text;
     assert result fields are populated.
   - `test_r04_cache_hit_skips_network` — pass a fake cache object with `exists()=True`;
     assert pull returns None without any httpx call.
   - `test_r05_refresh_bypasses_cache` — cache `exists()=True`, `refresh=True`; assert
     network is called.
   - `test_r06_network_error_raises_fetch_error` — mock httpx to raise `httpx.ConnectError`;
     assert `FetchError` is raised.
   - `test_r07_empty_text_fallback` — mock Article returning empty text; mock readability
     returning content; assert result.text is non-empty.

4. Run `uv run pytest tests/test_fetch.py -v` — all green.

## Commit message
feat: add fetch layer with robots.txt and newspaper4k (v0.3.0)
