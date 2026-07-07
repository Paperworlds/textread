---
id: '011'
title: textaccounts profile integration — --profile flag and default_profile config
repo: textread
model: sonnet
budget_usd: 1.50
phase: textread
depends_on: ['010']
---

# 011 — textaccounts profile integration

## Context

The CLI backend (prompt 010) shells out to `claude -p`. Claude CLI picks its account
from `CLAUDE_CONFIG_DIR`. textaccounts manages multiple Claude accounts and exposes
`env_for_profile(name) -> dict[str, str]` which returns `{"CLAUDE_CONFIG_DIR": "/path"}`.

By passing that env dict to `subprocess.run`, we can direct the agent call to a
specific Claude account without touching the shell environment. Useful when the active
account (set by `ta switch`) differs from the account you want textread to use, or when
running textread from a script with no active profile.

This only applies to the `cli` backend — the `sdk` backend uses `ANTHROPIC_API_KEY`
from env and is unaffected.

## Requirements

- R01: WHEN `textread read <url> --profile <name>` is passed, THE SYSTEM SHALL resolve
  the profile via textaccounts and inject its env into the `claude -p` subprocess.
- R02: WHEN `default_profile` is set in config, THE SYSTEM SHALL use it as the default
  profile for CLI backend calls (equivalent to always passing `--profile <default_profile>`).
- R03: WHEN `--profile` is passed with the `sdk` backend, THE SYSTEM SHALL print
  `[WARN] --profile has no effect with sdk backend` to stderr and proceed normally.
- R04: WHEN `--profile <name>` names a profile that does not exist, THE SYSTEM SHALL
  print `[ERROR] Unknown profile: <name>` to stderr and exit 1.
- R05: WHEN textaccounts is not installed, THE SYSTEM SHALL degrade gracefully — ignore
  `--profile` and `default_profile`, print `[WARN] textaccounts not installed — profile
  ignored` to stderr.
- R06: WHEN neither `--profile` nor `default_profile` is set, THE SYSTEM SHALL not
  modify the subprocess env — inherits the caller's env as today.
- R07: WHEN `default_profile` is absent from config, THE SYSTEM SHALL default to `None`
  (no profile injection).

## Design

### Resolving profile env

Add a helper in `agent.py` (or a new thin `profile.py` module):

```python
def _resolve_profile_env(profile: str | None) -> dict[str, str]:
    """Return env overrides for the given profile name, or {} if none."""
    if profile is None:
        return {}
    try:
        from textaccounts.api import env_for_profile, list_profiles
    except ImportError:
        import sys
        print("[WARN] textaccounts not installed — profile ignored", file=sys.stderr)
        return {}
    profiles = list_profiles()
    if profile not in [p.name for p in profiles]:
        raise AgentError(f"Unknown profile: {profile}")
    return env_for_profile(profile)
```

textaccounts is an **optional** import — textread does not declare it as a dependency.
If not installed, the feature degrades silently (R05).

### _evaluate_cli changes

Accept `profile_env: dict[str, str]` and merge into subprocess env:

```python
def _evaluate_cli(url, raw, context, model, profile_env=None):
    ...
    env = {**os.environ, **(profile_env or {})}
    result = subprocess.run(
        ["claude", "-p", full_prompt, "--model", model_id, "--output-format", "text"],
        capture_output=True, text=True, timeout=120,
        env=env,
    )
```

### evaluate() signature

```python
def evaluate(
    url: str,
    raw: str,
    context: ReadContext,
    model: str = "haiku",
    backend: str = "sdk",
    profile: str | None = None,
) -> Mapping:
    if backend == "cli":
        profile_env = _resolve_profile_env(profile)
        return _evaluate_cli(url, raw, context, model, profile_env)
    if profile is not None:
        import sys
        print("[WARN] --profile has no effect with sdk backend", file=sys.stderr)
    return _evaluate_sdk(url, raw, context, model)
```

### config.py changes

Add `default_profile: str | None = None` to `TextreadConfig` and `"default_profile"`
to `_KNOWN_FIELDS`.

### cli.py changes

Add `--profile` option to `read_cmd` and `remap_cmd`:

```python
@click.option("--profile", default=None, help="textaccounts profile for claude -p calls.")
```

Resolve effective profile:
```python
profile = profile or cfg.default_profile
```

Pass to `agent.evaluate(..., profile=profile)`.

### pyproject.toml

Do NOT add textaccounts to `dependencies`. It remains optional. Add a comment:

```toml
# Optional: textaccounts (for --profile support)
# uv tool install textaccounts
```

## Steps

1. Update `src/textread/agent.py`:
   - Add `_resolve_profile_env(profile)` helper with optional textaccounts import.
   - Update `_evaluate_cli` to accept and merge `profile_env`.
   - Update `evaluate()` to accept `profile: str | None = None` and dispatch.
   - SDK backend: warn and ignore profile (R03).

2. Update `src/textread/config.py`:
   - Add `default_profile: str | None = None` to `TextreadConfig`.
   - Add `"default_profile"` to `_KNOWN_FIELDS`.

3. Update `src/textread/cli.py`:
   - Add `--profile` option to `read_cmd` and `remap_cmd`.
   - Resolve `profile = profile or cfg.default_profile`.
   - Pass to `agent.evaluate`.

4. Update `tests/test_agent.py`:
   - `test_r01_profile_injects_env` — monkeypatch `textaccounts.api.env_for_profile`
     to return `{"CLAUDE_CONFIG_DIR": "/tmp/test"}` and `list_profiles` to return a
     profile named "personal"; assert subprocess.run called with env containing that key.
   - `test_r02_unknown_profile_raises` — monkeypatch list_profiles to return []; assert
     AgentError raised with "Unknown profile".
   - `test_r03_textaccounts_not_installed` — monkeypatch import to raise ImportError;
     assert empty env returned and warning printed to stderr.
   - `test_r04_sdk_backend_warns_on_profile` — call `evaluate(..., backend="sdk",
     profile="personal")`; assert [WARN] printed to stderr, SDK called normally.
   - `test_r05_no_profile_no_env_change` — call `_resolve_profile_env(None)`; assert
     returns `{}`.

5. Update `tests/test_config.py`:
   - `test_default_profile_none` — empty config; assert `cfg.default_profile is None`.
   - `test_default_profile_set` — write `default_profile: personal`; assert loaded.

6. Update `tests/test_cli.py`:
   - `test_profile_flag_passed_to_agent` — monkeypatch `agent.evaluate`; invoke
     `read --via-cli --profile personal <url>`; assert called with `profile="personal"`.
   - `test_default_profile_from_config` — monkeypatch config to return
     `TextreadConfig(default_profile="work")`; invoke `read --via-cli <url>`;
     assert agent called with `profile="work"`.
   - `test_profile_with_sdk_backend_warns` — invoke `read --profile personal <url>`
     (no --via-cli); assert [WARN] in stderr, exit 0.

7. Run `uv run pytest tests/ -v` — all green.

8. Manual smoke tests:
   ```bash
   # List available profiles first
   ta list

   # Read with personal profile (CLI backend required)
   textread read https://github.com/paperworlds/textread --via-cli --profile personal

   # Set as default in config
   echo "agent_backend: cli\ndefault_profile: personal" > ~/.config/paperworlds/textread.yaml
   textread read https://example.com   # uses personal profile automatically

   # Unknown profile
   textread read https://example.com --via-cli --profile nonexistent
   # → [ERROR] Unknown profile: nonexistent
   ```

## Commit message
feat: textaccounts profile integration for cli backend (v0.1.3)
