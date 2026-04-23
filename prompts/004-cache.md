---
id: '004'
title: Cache layer
repo: textread
model: haiku
budget_usd: 0.75
phase: textread
depends_on: ['001']
---

# 004 — Cache layer

## Requirements

- R01: WHEN `cache.path(url)` is called, THE SYSTEM SHALL return a `Path` of the form
  `{cache_root}/{slug}-{hash6}/` where `slug` is derived from the URL path and `hash6`
  is the first 6 characters of the SHA-256 of the full URL.
- R02: WHEN `cache.exists(url)` is called, THE SYSTEM SHALL return `True` if and only
  if `cache.path(url) / "raw.meta.json"` exists on disk.
- R03: WHEN `cache.put(url, result)` is called with a `FetchResult`, THE SYSTEM SHALL
  write `raw.html` (or `raw.txt` depending on content_type), `raw.md` (the extracted
  article text as plain markdown), and `raw.meta.json` into `cache.path(url)`,
  creating the directory if needed.
- R03b: WHEN `cache.get_markdown(url)` is called and the cache entry exists, THE SYSTEM
  SHALL return the contents of `raw.md` as a string.
- R04: WHEN `cache.get_meta(url)` is called and the cache entry exists, THE SYSTEM SHALL
  return the parsed `raw.meta.json` as a dict.
- R05: WHEN `cache.get_raw(url)` is called and the cache entry exists, THE SYSTEM SHALL
  return the raw file contents as a string.
- R06: WHEN `cache.write_mapping(url, mapping)` is called, THE SYSTEM SHALL serialise
  `mapping` to YAML and write it to `cache.path(url) / "mapping.yaml"`.
- R07: WHEN `cache.read_mapping(url)` is called and `mapping.yaml` exists, THE SYSTEM
  SHALL return the parsed mapping as a dict.
- R08: WHEN `textread cache list` is run, THE SYSTEM SHALL print one line per cached
  entry: `{slug}-{hash6}  {url}  {fetched_at}`.
- R09: WHEN `textread cache path <url>` is run, THE SYSTEM SHALL print the absolute
  cache directory path for that URL.
- R10: WHEN `textread cache clear` is run, THE SYSTEM SHALL delete all entries under
  `cache_root` and print the count of deleted entries.

## Design

### overview

`cache.py` is a pure I/O module — no network, no AI. It owns the two-tier layout:
`raw.*` is the immutable fetch archive, `mapping.yaml` is the regeneratable
interpretation. The slug+hash key gives human-readable directory names while
avoiding collisions. The `cache_group` Click group (show/path/clear) lives here
so `cli.py` can import and attach it.

### modules

- `src/textread/cache.py` — New file. All cache helpers + `cache_group` Click group.
- `tests/test_cache.py` — New file. File-system tests using `tmp_path`.

### data_structures

```python
# raw.meta.json schema
{
  "url": "https://example.com/article",
  "final_url": "https://example.com/article",
  "content_type": "text/html",
  "fetched_at": "2026-04-18T10:00:00Z"
}
```

Slug derivation:
- Take `urllib.parse.urlparse(url).path`, strip leading/trailing `/`.
- Replace all non-alphanumeric chars with `-`, collapse runs of `-`, strip edges.
- Truncate to 40 chars.
- Append `-` + first 6 chars of `hashlib.sha256(url.encode()).hexdigest()`.

### sequence

put_flow:
  1. Compute dir = `cache.path(url)`. Create with `mkdir(parents=True, exist_ok=True)`.
  2. Determine extension: `html` if `text/html` in content_type, else `txt`.
  3. Write `dir / f"raw.{ext}"` with the fetch result text (original fetched content).
  4. Write `dir / "raw.md"` with `result.text` (newspaper4k extracted article text —
     this is the cleaned markdown that the agent receives).
  5. Write `dir / "raw.meta.json"` with JSON of url, final_url, content_type, fetched_at.

cache_list:
  1. Glob `{cache_root}/*/raw.meta.json`.
  2. For each, load meta, print `{dir.name}  {meta["url"]}  {meta["fetched_at"]}`.

### degradation

Any I/O error on read operations raises `CacheError`. Write operations let filesystem
exceptions propagate — the caller (cli.py) handles them.

## Steps

1. Create `src/textread/cache.py`:
   - `_slug(url: str) -> str` — slug+hash derivation per `data_structures`.
   - `path(url: str, cfg: TextreadConfig | None = None) -> Path` — resolves
     `cache_root` from config or default, returns `Path(root) / _slug(url)`.
   - `exists(url: str, cfg=None) -> bool` (R02).
   - `put(url: str, result: FetchResult, cfg=None) -> Path` — writes raw files (R03).
   - `get_meta(url: str, cfg=None) -> dict` (R04).
   - `get_raw(url: str, cfg=None) -> str` (R05).
   - `get_markdown(url: str, cfg=None) -> str` (R03b) — reads `raw.md`.
   - `write_mapping(url: str, mapping: dict, cfg=None) -> None` (R06).
   - `read_mapping(url: str, cfg=None) -> dict | None` (R07).
   - `cache_group` Click group with `list`, `path <url>`, `clear` subcommands (R08-R10).

2. Create `tests/test_cache.py`:
   - All tests use `tmp_path` as `cache_root`; pass it via a minimal `TextreadConfig`.
   - `test_r01_slug_format` — assert slug matches expected pattern for a known URL.
   - `test_r01_slug_no_collision` — two different URLs produce different slugs.
   - `test_r02_exists_false_before_put` — assert exists() is False before any write.
   - `test_r03_put_creates_files` — put a FetchResult, assert raw file + meta exist.
   - `test_r02_exists_true_after_put` — exists() True after put.
   - `test_r04_get_meta_round_trip` — put then get_meta, assert dict equality.
   - `test_r05_get_raw_round_trip` — put then get_raw, assert text equality.
   - `test_r03b_get_markdown_round_trip` — put a FetchResult, get_markdown returns result.text.
   - `test_r06_write_mapping` — write a mapping dict, assert mapping.yaml exists.
   - `test_r07_read_mapping_round_trip` — write then read mapping, assert equality.
   - `test_r07_read_mapping_missing_returns_none` — read mapping when absent → None.

3. Run `uv run pytest tests/test_cache.py -v` — all green.

## Commit message
feat: add cache layer with slug+hash key and CLI subcommands (v0.4.0)
