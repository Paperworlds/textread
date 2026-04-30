---
id: '012'
title: browser fetch backend for JS-heavy / SPA pages
repo: textread
model: sonnet
budget_usd: 2.50
phase: textread
depends_on: []
---

# 012 — browser fetch backend

## Context

`fetch.pull()` runs newspaper4k → readability fallback. Both work on the **initial
HTML** the server returns. For client-rendered pages (Substack hydrate, Medium
gates, Vercel/Next.js SPAs, anything heavy on framework JS), the initial HTML is a
near-empty shell — we end up writing junk into `raw.md` and the agent verdicts get
worse. Today the only signals are silent: a thin `text` field, or no article
element to extract from.

Add a third fetch backend that drives a real browser, lets the page hydrate, and
then extracts the rendered DOM. Mirror the existing `pdf_backend: native | marker`
pattern with `fetch_backend: native | browser`.

**Explicit non-goal:** X.com `/article/` URLs. Those require a logged-in session
and aggressive bot-detection bypass, which is brittle and TOS-violating. The
backend will simply fail (or return junk) on X — that's expected. Manual workaround
documented in README: copy text → save markdown → `textread add file.md`.

## Requirements

- R01: WHEN `fetch_backend: browser` is set in config, THE SYSTEM SHALL route
  `fetch.pull()` through the browser driver instead of newspaper4k.
- R02: WHEN `--via-browser` is passed to `textread read` or `textread pull`,
  THE SYSTEM SHALL use the browser backend regardless of config (per-call override).
- R03: WHEN the browser backend is invoked AND `browser-harness` is not
  installed, THE SYSTEM SHALL raise `FetchError("browser backend requires
  browser-harness — pip install browser-harness")` and exit non-zero.
- R04: WHEN robots.txt disallows the URL, THE SYSTEM SHALL raise `FetchBlocked`
  *before* spawning a browser — robots is checked first regardless of backend.
- R05: WHEN the browser navigates to the URL, THE SYSTEM SHALL wait for
  `networkidle` (or equivalent) up to 15s, then extract `document.body.innerText`
  filtered through readability.
- R06: WHEN navigation fails or times out, THE SYSTEM SHALL raise `FetchError`
  with the underlying reason and ensure no browser process is leaked.
- R07: WHEN extraction succeeds, THE SYSTEM SHALL return the same `FetchResult`
  shape used by the native backend (url, final_url, text, content_type,
  fetched_at) — callers (cache, agent) need no changes.
- R08: WHEN browser-harness fails to attach to an existing Chrome AND no headless
  fallback succeeds, THE SYSTEM SHALL raise `FetchError` with a clear
  remediation hint ("start Chrome with --remote-debugging-port=9222 or install
  browser-harness with [headless] extra").
- R09: The browser module SHALL be imported lazily (top-level `import textread`
  must not load Playwright / browser-harness / asyncio overhead).
- R10: WHEN `fetch_backend` config value is invalid (not `native` or `browser`),
  THE SYSTEM SHALL warn and fall back to `native`, matching `pdf_backend`'s
  validation pattern in `config.py`.

## Design

### Module layout

```
src/textread/
  fetch.py            ← unchanged dispatcher entrypoint, picks backend
  fetch_browser.py    ← new — lazy-imports browser-harness, exposes pull_browser()
```

`fetch.pull()` becomes a thin dispatcher:

```python
def pull(url, refresh=False, cache=None, backend: str = "native") -> FetchResult | None:
    if cache is not None and not refresh and cache.exists(url):
        return None
    if not _robots_allowed(url):       # R04
        raise FetchBlocked(url)
    if backend == "browser":
        from textread.fetch_browser import pull_browser   # R09: lazy
        return pull_browser(url)
    return _pull_native(url)           # current newspaper4k path, factored out
```

### fetch_browser.py sketch

```python
"""Browser-driven fetch for JS-heavy pages. Lazy import; do not load at module top level."""
from __future__ import annotations
from datetime import datetime, timezone
from textread.fetch import FetchResult, FetchError, _strip_tags, UA

def pull_browser(url: str, timeout_s: float = 15.0) -> FetchResult:
    try:
        import browser_harness  # type: ignore[import-untyped]
    except ImportError as exc:
        raise FetchError(
            "browser backend requires browser-harness — pip install browser-harness"
        ) from exc

    try:
        with browser_harness.session(user_agent=UA) as session:
            page = session.goto(url, wait_until="networkidle", timeout=timeout_s)
            html = page.content()
            final_url = page.url
    except Exception as exc:
        raise FetchError(f"browser fetch failed: {exc}") from exc

    from readability import Document
    text = _strip_tags(Document(html).summary())
    if not text.strip():
        raise FetchError(f"browser returned empty content for {url}")

    return FetchResult(
        url=url,
        final_url=final_url,
        text=text,
        content_type="text/html",
        fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
```

(Exact `browser_harness` API may differ — verify against
https://github.com/browser-use/browser-harness when implementing. The session/goto
shape above is the design contract; adapt syntax to match.)

### Config changes

`config.py`:

```python
@dataclasses.dataclass
class TextreadConfig:
    ...
    fetch_backend: str = "native"   # native | browser

# in load():
if "fetch_backend" in known and known["fetch_backend"] not in {"native", "browser"}:
    print(f"[WARN] fetch_backend must be 'native' or 'browser' — got {known['fetch_backend']!r}, defaulting to 'native'")
    known["fetch_backend"] = "native"
```

Add `"fetch_backend"` to `_KNOWN_FIELDS`.

### CLI changes

Add `--via-browser` to `read_cmd` and `pull_cmd` (mutually exclusive with
`--via-cli` is unrelated — `--via-browser` only affects fetch, `--via-cli`
only affects agent backend).

```python
@click.option("--via-browser", "via_browser", is_flag=True, default=False,
              help="Use the headless browser fetch backend (overrides fetch_backend config).")
```

In each command, resolve effective backend:
```python
fetch_backend = "browser" if via_browser else cfg.fetch_backend
result = fetch.pull(url, cache=_CacheProxy(cfg), backend=fetch_backend)
```

### pyproject.toml

Do NOT add `browser-harness` to required `dependencies`. Add an optional extra:

```toml
[project.optional-dependencies]
browser = ["browser-harness>=0.1"]
```

Document in README: `pip install textread[browser]` or `uv tool install textread --with browser-harness`.

### README

Add to Roadmap section: change "[ ] Browser fetch backend for JS-heavy / SPA pages"
to a new section under Configuration:

```markdown
### Browser fetch backend (optional)

For JS-heavy / SPA pages (Substack, Medium, Vercel apps) that the default
fetch returns blank or truncated text for, install the optional dep:

    pip install textread[browser]

Then either set `fetch_backend: browser` in `~/.config/paperworlds/textread.yaml`
to use it for every fetch, or pass `--via-browser` ad-hoc:

    textread read https://some-spa-blog.com --via-browser

**Does not work for X.com `/article/` URLs** — those require a logged-in
session and aggressive bot-detection bypass. Save the article text manually
and use `textread add ~/file.md` instead.
```

## Steps

1. Refactor `fetch.py`:
   - Extract current newspaper4k+readability body into `_pull_native(url)`.
   - Make `pull()` a thin dispatcher that takes `backend: str = "native"`.
   - Robots check stays at the top, before backend dispatch.

2. Create `src/textread/fetch_browser.py`:
   - Lazy-import `browser_harness`.
   - Implement `pull_browser(url, timeout_s=15.0) -> FetchResult` per sketch.
   - Map all browser exceptions to `FetchError`.
   - Ensure browser context is cleanly closed (use `with`).

3. Update `src/textread/config.py`:
   - Add `fetch_backend: str = "native"` to `TextreadConfig`.
   - Add `"fetch_backend"` to `_KNOWN_FIELDS`.
   - Add validation in `load()` mirroring `pdf_backend`.

4. Update `src/textread/cli.py`:
   - Add `--via-browser` to `read_cmd` and `pull_cmd`.
   - Resolve `fetch_backend = "browser" if via_browser else cfg.fetch_backend`.
   - Pass to `fetch.pull(..., backend=fetch_backend)`.

5. Update `pyproject.toml`:
   - Add `[project.optional-dependencies]` with `browser = ["browser-harness>=0.1"]`.

6. Tests — `tests/test_fetch.py`:
   - `test_r01_browser_backend_routes_correctly` — monkeypatch
     `textread.fetch_browser.pull_browser` to return a stub `FetchResult`;
     call `fetch.pull(url, backend="browser")`; assert the stub was called and
     newspaper4k path was NOT invoked.
   - `test_r03_browser_missing_dep_raises` — monkeypatch the lazy import to
     raise `ImportError`; assert `FetchError` with "requires browser-harness"
     in the message.
   - `test_r04_robots_blocked_before_browser_spawn` — robots disallows;
     monkeypatch `pull_browser` to a tracker that records calls; assert
     `FetchBlocked` raised AND tracker not called.
   - `test_r07_browser_returns_fetchresult_shape` — monkeypatch
     `pull_browser` to return canned `FetchResult`; assert dispatcher
     returns it unchanged.
   - `test_r09_lazy_import` — assert `import textread.fetch` does NOT import
     `browser_harness` (check `sys.modules` before/after).

   Tests for `fetch_browser.py` itself (R05, R06, R08) require monkeypatching
   the `browser_harness` module — keep them light, focus on the error-mapping
   behavior (timeout → FetchError, attach failure → FetchError with hint).
   Do NOT spin up a real browser in tests.

7. Tests — `tests/test_config.py`:
   - `test_fetch_backend_default_native` — empty config; `cfg.fetch_backend == "native"`.
   - `test_fetch_backend_browser_loaded` — write `fetch_backend: browser`; assert loaded.
   - `test_fetch_backend_invalid_falls_back` — write `fetch_backend: phantom`;
     assert warning printed AND `cfg.fetch_backend == "native"`.

8. Tests — `tests/test_cli.py`:
   - `test_via_browser_flag_routes_browser_backend` — monkeypatch `fetch.pull`;
     invoke `read --via-browser <url>`; assert called with `backend="browser"`.
   - `test_default_fetch_backend_from_config` — monkeypatch config to return
     `fetch_backend="browser"`; invoke `read <url>`; assert called with
     `backend="browser"`.
   - `test_pull_via_browser_flag` — same as above but for the `pull` command.

9. Update `README.md`:
   - Move the roadmap line into a new "Browser fetch backend (optional)"
     subsection under Configuration.
   - Document the X.com caveat explicitly.
   - Document the `pip install textread[browser]` install path.

10. Update `CHANGELOG.md`:
    - New `## v0.4.0` section (minor bump — new optional dependency surface).
    - Bullets: backend introduced, `--via-browser` flag, X.com non-goal called
      out, install instructions.

11. Bump version in `pyproject.toml` to `0.4.0`. Run `uv sync`.

12. Run `uv run pytest tests/ -v` — all green.

13. Manual smoke test (only if browser-harness is installed):
    ```bash
    pip install browser-harness
    # On a known SPA (a Substack URL is a good probe):
    textread read https://some-substack.example/post --via-browser
    # Verify raw.md contains article text rather than the empty shell.

    # Negative path: confirm X article still doesn't work
    textread read https://x.com/SomeUser/article/12345 --via-browser
    # Expected: FetchError or empty content — that's by design.
    ```

14. Commit + tag:
    ```bash
    git -c commit.gpgsign=false commit -m "feat: browser fetch backend for JS-heavy pages (v0.4.0)"
    git tag v0.4.0
    git push && git push --tags
    ```

## Out of scope (for this prompt)

- X.com login / cookie persistence / stealth plugins. Documented non-goal.
- Playwright as alternative driver. Can be added later as a second `[playwright]`
  extra; the architecture already isolates the driver behind `fetch_browser.py`.
- Caching of browser sessions across multiple fetches in one `pull` run.
  Worth a follow-up — current design spawns/attaches per URL, which works but
  is slower than necessary at scale.
- Cookie / auth header injection for paywalled content. Out of scope; defer
  until a concrete user workflow needs it.

## Commit message

feat: browser fetch backend for JS-heavy / SPA pages (v0.4.0)

Adds an optional fetch_backend: browser path via browser-harness for
client-rendered pages (Substack, Medium, Vercel apps) where the default
newspaper4k path returns blank shells. Mirrors the pdf_backend pattern;
lazy import keeps default users on the same install footprint.

X.com /article/ URLs are an explicit non-goal — login + bot-detection
make this brittle. Manual workaround documented in README.
