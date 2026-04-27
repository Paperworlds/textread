# Changelog

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
