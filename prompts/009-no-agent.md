---
id: '009'
title: --no-agent flag and agent_enabled config option
repo: textread
model: haiku
budget_usd: 1.00
phase: textread
depends_on: ['006']
---

# 009 — --no-agent flag and agent_enabled config option

## Context

`textread read <url>` always calls Claude, which requires `ANTHROPIC_API_KEY`.
Users who just want to fetch-and-cache a URL, or who have no key configured,
are blocked. Two additions fix this:

1. `--no-agent` flag on `textread read` — fetch and cache only, skip the agent call.
2. `agent_enabled` config key in `~/.config/paperworlds/textread.yaml` — set to
   `false` to make `--no-agent` the default for all reads.

## Requirements

- R01: WHEN `textread read <url> --no-agent` is run, THE SYSTEM SHALL fetch (or
  use cache) and write `raw.<ext>` + `raw.meta.json` + `raw.md`, then print
  `[CACHED] <url>` to stdout and exit 0. The agent SHALL NOT be called.
- R02: WHEN `agent_enabled: false` is set in config, THE SYSTEM SHALL behave as
  if `--no-agent` was passed on every `textread read` invocation.
- R03: WHEN `--no-agent` is passed alongside `--model`, THE SYSTEM SHALL ignore
  `--model` (no agent call, model irrelevant) without error.
- R04: WHEN `--no-agent` is passed and the URL is already cached, THE SYSTEM SHALL
  print `[CACHED] <url>` and exit 0 without re-fetching (unless `--refresh` also passed).
- R05: WHEN `textread remap <url> --no-agent` is run, THE SYSTEM SHALL print
  `[ERROR] --no-agent has no effect on remap` to stderr and exit 1.
- R06: WHEN `agent_enabled` is absent from config, THE SYSTEM SHALL default to `true`.
- R07: WHEN the config is saved via `textread config` (future), THE SYSTEM SHALL
  preserve the `agent_enabled` field.

## Design

### config.py changes

Add `agent_enabled: bool = True` to `TextreadConfig` and `"agent_enabled"` to
`_KNOWN_FIELDS`. `load()` should cast the YAML value to bool.

```python
@dataclasses.dataclass
class TextreadConfig:
    cache_root: str = "~/.textread/cache"
    default_model: str = "haiku"
    context_path: str = "~/.config/paperworlds/read-context.yaml"
    agent_enabled: bool = True
```

### cli.py changes

Add `--no-agent` flag to `read_cmd`. Resolve effective `run_agent` bool:

```python
@click.option("--no-agent", "no_agent", is_flag=True, default=False,
              help="Fetch and cache only — skip the agent call.")

# in read_cmd body:
run_agent = cfg.agent_enabled and not no_agent
```

After `cache.put(url, result, cfg)` / cache-hit path:
```python
if not run_agent:
    click.echo(f"[CACHED] {url}")
    return

# ... existing agent call block ...
```

No other changes to the fetch or cache path — those run regardless.

### remap_cmd

Add `--no-agent` flag that immediately errors (R05). One line before any logic:

```python
if no_agent:
    click.echo("[ERROR] --no-agent has no effect on remap", err=True)
    sys.exit(1)
```

## Steps

1. Update `src/textread/config.py`:
   - Add `agent_enabled: bool = True` to `TextreadConfig`.
   - Add `"agent_enabled"` to `_KNOWN_FIELDS`.
   - Cast loaded value: `bool(data.get("agent_enabled", True))`.

2. Update `src/textread/cli.py`:
   - Add `--no-agent` flag to `read_cmd`.
   - Compute `run_agent = cfg.agent_enabled and not no_agent`.
   - Gate the agent block on `run_agent`.
   - Print `[CACHED] {url}` and return when `not run_agent`.
   - Add `--no-agent` to `remap_cmd` with immediate error exit.

3. Update `tests/test_config.py`:
   - `test_r06_agent_enabled_default` — load empty config; assert `cfg.agent_enabled is True`.
   - `test_agent_enabled_false` — write `agent_enabled: false` to config file; assert `cfg.agent_enabled is False`.

4. Update `tests/test_cli.py`:
   - `test_r01_no_agent_flag_skips_agent` — invoke `read --no-agent <url>`; assert
     agent.evaluate NOT called; assert `[CACHED]` in output.
   - `test_r02_config_agent_disabled_skips_agent` — monkeypatch `load_config` to return
     `TextreadConfig(agent_enabled=False)`; invoke `read <url>`; assert agent not called.
   - `test_r03_no_agent_ignores_model` — invoke `read --no-agent --model sonnet <url>`;
     assert no error, agent not called.
   - `test_r04_no_agent_cache_hit` — cache.exists returns True; invoke `read --no-agent <url>`;
     assert fetch.pull NOT called (cache hit + no agent = just print).
   - `test_r05_remap_no_agent_errors` — invoke `remap --no-agent <url>`; assert exit code 1
     and `[ERROR]` in stderr.

5. Run `uv run pytest tests/ -v` — all green.

6. Manual smoke test (no API key needed):
   ```bash
   textread read https://github.com/paperworlds/textread --no-agent
   # → [CACHED] https://github.com/paperworlds/textread

   # also test via config:
   echo "agent_enabled: false" >> ~/.config/paperworlds/textread.yaml
   textread read https://example.com
   # → [CACHED] https://example.com
   ```

## Commit message
feat: add --no-agent flag and agent_enabled config option (v0.1.1)
