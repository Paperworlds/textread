# Changelog

## v0.9.1

- fix(fetch): catch `ArticleBinaryDataException` from newspaper4k and fall through to the readability + httpx path. Cursor's blog (and any site sending `Content-Disposition: inline`) was being misclassified as binary, since newspaper's `is_binary_url()` treats *any* Content-Disposition header as an attachment download. Regression test added.

## v0.9.0

- BREAKING: all textread state and config now lives under `~/.local/paperworlds/textread/`. Previous paths (`~/.config/paperworlds/textread.yaml`, `~/.local/state/paperworlds/textread/`, `~/.textread/`) are no longer read.
- Layout: `~/.local/paperworlds/textread/{config.yaml, read-context.yaml, inbox.jsonl, cache/, digests/, log.yaml}`.
- Single-user move — no migration command; data was moved by hand. Update `~/.local/paperworlds/textread/config.yaml` if you set custom `cache_root`/`context_path`.
- Drive-by: fixed stale `test_r02_user_agent_header` that still asserted the pre-v0.6.1 UA string.

## v0.8.0

- New: `textread search QUERY` — grep across saved digests + cached article markdown. Regex supported, case-insensitive by default. `--in digests|cache|all`, `--limit N`. Yellow-highlights matches in snippet context.
- v1 is grep-only. Semantic tier (Semble integration as optional dep) deferred — tracked in textforums thread `proposal-textread-search-semble-integration-as-optional-dep-`.

## v0.7.1

- New: `textread digests audit` — per-domain discard rate across all digests. Surfaces which sources keep producing items you toss, so you can tune your inbox before the digest runs.
- `--min-count N` filters out one-off domains (default 2). Sorted by discard rate desc, colored red ≥50%, yellow ≥25%, green below.

## v0.7.0

- New: `textread digests stats` — counts by status, all-time acceptance rate (reviewed / decided), trailing 30-day discard rate. Turns the review/discard signal you've been collecting into a legible measurement.
- Smallest viable shape. `audit` (patterns in discarded items) deferred until `stats` is proven useful.

## v0.6.1

- Fix: fetch layer now uses a real Chrome user-agent string instead of `textread/<version>`. Sites with cheap bot filters (HashiCorp blog, most corporate sites behind Cloudflare's basic rules) no longer 429.
- Sites with JS challenges or full bot managers will still fail — those need a headless browser.

## v0.6.0

- New: `textread raindrop add URL [URL ...]` — push URLs into the configured collection.
- New: `textread raindrop add --file path.yaml` — batch import from a YAML list. Entries may be bare URL strings or `{url, title?, tags?}` dicts.
- `raindrop.create_item()` added to the client module.

## v0.5.2

- Fix: `--profile` no longer crashes with `AttributeError: 'str' object has no attribute 'name'`. `textaccounts.api.list_profiles()` returns `list[str]` per `textaccounts-api-v0-2`; the validation code was treating entries as objects with a `.name` attribute (likely a v0.1 holdover).
- Test updated to mock the spec-compliant return shape.

## v0.5.1

- Revert v0.5.0's hard-dep on textaccounts — it is once again an *optional* extra (`pip install textread[profiles]` or `uv add textaccounts`)
- New behavior: when `--profile` is requested without textaccounts installed, raise `AgentError` with a clear install hint (no more silent fallback that bills the wrong account)
- `--profile` omitted + textaccounts missing → silent no-op, same as before

## v0.5.0

- textread is now a formal consumer of `textaccounts-api-v0-2` — `textaccounts` is a hard dependency, so `--profile NAME` works out of the box (no more `[WARN] textaccounts not installed`)
- `default_profile` config key now defaults to `"default"` (was `None`); set in `~/.config/paperworlds/textread.yaml` to pick a different profile machine-wide

## v0.4.2

- `textread learnings list` — fix column alignment when some entries lack a `date:` field (date column now fixed-width)

## v0.4.1

- Compendium files (top-level keys mapping to lists of records, e.g. `snippets:`, `audits:`, `plans:`) are now expanded into individual learnings, named `{file}:{record_id}` and tagged with the section name
- `textread learnings show <id>` resolves by record id too, not just filename stem
- `show` for compendium sub-records pretty-prints just that record (literal block scalars, no escape-sequence soup)

## v0.4.0

- `textread learnings list/show/search` — browse small YAML knowledge notes (recursive)
- `learnings_path` config key (default `~/.local/learnings`)
- Agent system prompt now includes a compact list of learning titles+tags so verdicts can reference prior troubleshooting notes

## v0.3.6

- `textread raindrop collect` — move uncategorized items into the configured collection
- `textread raindrop init` — create the configured collection if it doesn't exist

## v0.3.5

- `textread raindrop peek` — list items waiting in the configured collection without ingesting; warns if anything is sitting uncategorized

## v0.3.4

- `textread config set <key> <value>` — write a config value from the CLI (use `null` to clear)
- `textread config get <key>` — print the current value of a single key
- `textread config show` — print all current config values

## v0.3.3

- `textread digest` clears the inbox after a successful digest by default; use `--keep` to retain items
- `textread inbox clear` — flush the inbox without running a digest

## v0.3.0

- `textread pull` now moves processed items into a dedicated `digested` Raindrop collection (auto-created if missing), instead of dropping them into Unsorted. Configurable via `raindrop_digested_collection` in `~/.config/paperworlds/textread.yaml`. `--delete` still permanently removes.
- `textread recover --since DATE` now scans both Trash and the digested collection (deduped by item id), so already-processed items can be re-ingested without manual moves in the Raindrop UI.

## v0.2.3

- `textread recover --since YYYY-MM-DD` — restore Raindrop Trash items back into the `textread` collection (default: today, UTC); run `textread pull` afterward to re-ingest
- Fix: `digest` crash on non-`AgentError` exception (e.g. missing `ANTHROPIC_API_KEY`) no longer strands items — `finish_digest(clear=False)` now runs in a `finally`, restoring locked items to the inbox
- Fix: stale-lock recovery in `inbox.lock_info()` no longer deletes orphaned `inbox.processing.jsonl` entries — they are restored to the pending inbox

## v0.3.2

- `textread pull` moves unfetchable items to a `blocked` Raindrop collection instead of silently skipping them
- `raindrop_blocked_collection` config key (default: `blocked`) — auto-created if missing

## v0.3.1

- `textread pull` now routes Raindrop-hosted PDFs through the PDF pipeline instead of failing with "binary data" error
- Detection uses Raindrop's `type: document` field, `.pdf` extension, or `application/pdf` in URL

## v0.2.2

- `textread pull` now moves processed items to Raindrop Unsorted instead of deleting them
- `textread pull --delete` flag for permanent deletion

## v0.2.1

- `textread pull` — drain a Raindrop.io collection into the inbox: fetches each URL, caches it, adds to inbox, deletes from Raindrop
- `raindrop_token` and `raindrop_collection` config keys
- README: Raindrop.io setup instructions

## v0.2.0

- Per-item locking during digest: items being processed move to `inbox.processing.jsonl`; `add` is always open and never blocked
- `textread inbox` shows locked items separately with pid and start time
- `textread digest` acquires the lock at start, releases on finish or error; a second concurrent digest is rejected
- Stale lock auto-recovery: if the digest process dies, the lock is removed and items restored on next `inbox` or `add` call
- `textread digests discard <id>` — mark a digest as discarded (shown in red in `digests list`)

## v0.1.9

- `textread digests list` — list all saved digests with `pending` / `reviewed` status and source count
- `textread digests show <id>` — page through a saved digest (e.g. `2026-04-27`)
- `textread digests review <id>` — mark a digest as reviewed (writes sidecar `.state` file)
- Moved digest save logic into `src/textread/digests.py` module

## v0.1.8

- `textread digest` auto-saves output to `~/.local/state/paperworlds/textread/digests/YYYY-MM-DD.md`
- Saved file includes a `## Sources` header listing which items were digested
- Collision-safe naming: second digest of the day gets `YYYY-MM-DD-2.md` etc.

## v0.1.7

- `textread add <source>` — fetch/cache a URL, PDF, or local `.md` file and append it to the inbox
- `textread inbox` — list items currently pending digest
- `textread digest` — synthesize all inbox items via Claude: per-item summaries, themes & connections, brainstorm; `--clear` flushes inbox after
- Inbox stored at `~/.local/state/paperworlds/textread/inbox.jsonl` (one JSON entry per line)

## v0.1.6

- ci: install `libxml2-dev` and `libxslt1-dev` before `uv sync` — `lxml==5.4.0` (required transitively by `readability-lxml`) had no prebuilt wheel for Python 3.14 on Linux and was failing source-build on the runner

## v0.1.5

- `textread pdf <file|url>` — extract PDF to markdown via pymupdf4llm, then run agent pipeline
- `textread url <url>` — explicit web URL command (what `read` did before)
- `textread read <source>` — smart router: auto-detects PDF vs web URL, logs `[READ] pdf →` or `[READ] url →`
- `pdf_backend: native | marker` config key (marker backend planned, native is pymupdf4llm)
- `--backend native|marker` and `--pages 1-5` flags on `textread pdf`

## v0.1.4

- `textread install` — writes shell completions for fish, bash, or zsh (auto-detects shell)
- Version output follows Paperworlds convention: `textread, version X.Y.Z (githash)` with `-V` alias
- nltk warning from `newspaper4k` suppressed on import
- Justfile: `just test`, `just install`, `just version`
- GitHub Actions CI: runs `pytest` on every push and pull request
- README: Install, How it works, Roadmap, Part of Paperworlds sections

## v0.1.3

- `textread read --profile <name>` injects a textaccounts profile env into `claude -p` subprocess
- `default_profile` config key sets a default profile for all CLI backend calls
- `--profile` with `sdk` backend prints `[WARN]` and proceeds — no breakage

## v0.1.2

- `textread read --via-cli` shells out to `claude -p` instead of calling the Anthropic SDK — no API key needed
- `agent_backend: cli` config key makes the CLI backend the default
- `--via-cli` and `--no-agent` are mutually exclusive — exits 1 with `[ERROR]`

## v0.1.1

- `textread read --no-agent` fetches and caches without calling Claude
- `agent_enabled: false` config key makes `--no-agent` the default

## v0.1.0

- Initial release
- `textread read <url>` — fetch, cache, agent evaluate, print verdict
- `textread remap <url>` — re-run agent on cached content
- `textread context` — manage read context (role, stack, projects)
- `textread cache` — inspect and manage the local cache
- Three-tier cache: raw binary, `raw.md` (cleaned markdown), `mapping.yaml`
- Config at `~/.config/paperworlds/textread.yaml`
- Context at `~/.config/paperworlds/read-context.yaml`
