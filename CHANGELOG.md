# Changelog

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
