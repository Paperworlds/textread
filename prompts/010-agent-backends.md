---
id: '010'
title: Agent backend selection — sdk (default) vs cli (claude -p)
repo: textread
model: sonnet
budget_usd: 2.00
phase: textread
depends_on: ['009']
---

# 010 — Agent backend selection — sdk vs cli

## Context

`agent.py` currently calls the Anthropic SDK directly, which requires
`ANTHROPIC_API_KEY` in env. Users who have Claude Code installed but no
separate API key configured are blocked. Adding a `cli` backend shells
out to `claude -p` instead — same auth Claude Code uses, no extra key.

Two additions:
1. `agent_backend: sdk | cli` config key in `~/.config/paperworlds/textread.yaml`.
2. `--via-cli` flag on `textread read` and `textread remap` that forces the CLI backend
   for a single invocation.

## Requirements

- R01: WHEN `agent_backend: sdk` is configured (the default), THE SYSTEM SHALL call
  the Anthropic SDK as today — no behaviour change.
- R02: WHEN `agent_backend: cli` is configured, THE SYSTEM SHALL call `claude -p
  "<prompt>"` via subprocess and parse the JSON response.
- R03: WHEN `--via-cli` flag is passed, THE SYSTEM SHALL use the CLI backend for
  that invocation regardless of config.
- R04: WHEN the CLI backend is selected and `claude` is not on PATH, THE SYSTEM SHALL
  print `[ERROR] claude binary not found — install Claude Code or use --no-agent` to
  stderr and exit 1.
- R05: WHEN the CLI backend returns output that cannot be parsed as valid JSON matching
  the Mapping schema, THE SYSTEM SHALL raise `AgentError` with the raw output (same
  behaviour as SDK backend).
- R06: WHEN `--via-cli` is passed alongside `--no-agent`, THE SYSTEM SHALL print
  `[ERROR] --via-cli and --no-agent are mutually exclusive` to stderr and exit 1.
- R07: WHEN the `claude -p` subprocess exits non-zero, THE SYSTEM SHALL raise
  `AgentError` with the stderr output.
- R08: WHEN `agent_backend` is absent from config, THE SYSTEM SHALL default to `sdk`.

## Design

### agent.py changes

Extract the SDK call into a private `_evaluate_sdk()` function. Add a parallel
`_evaluate_cli()` that shells out to `claude -p`. The public `evaluate()` function
dispatches based on a `backend` parameter.

```python
def evaluate(
    url: str,
    raw: str,
    context: ReadContext,
    model: str = "haiku",
    backend: str = "sdk",   # "sdk" | "cli"
) -> Mapping:
    if backend == "cli":
        return _evaluate_cli(url, raw, context, model)
    return _evaluate_sdk(url, raw, context, model)
```

#### _evaluate_sdk

Current implementation, extracted verbatim. No changes.

#### _evaluate_cli

```python
import shutil, subprocess

def _sanitize(text: str) -> str:
    """Strip null bytes and other control characters that would corrupt subprocess args."""
    return text.replace("\x00", "").replace("\r", "")

def _evaluate_cli(url, raw, context, model):
    if shutil.which("claude") is None:
        raise AgentError("claude binary not found — install Claude Code or use --no-agent")

    model_id = MODEL_ALIASES.get(model, model)
    system = _sanitize(_build_system_prompt(context))
    user_msg = _sanitize(f"URL: {url}\n\nContent:\n{raw[:MAX_CONTENT_CHARS]}")

    result = subprocess.run(
        ["claude", "-p", user_msg, "--system", system,
         "--model", model_id, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise AgentError(result.stderr.strip() or "claude -p exited non-zero")

    return _parse_mapping(result.stdout.strip())
```

Note: `subprocess.run` with a list (not `shell=True`) means shell injection is not a concern —
args are passed directly to the OS. `_sanitize` guards against null bytes and stray CR characters
that could corrupt argument parsing in some environments.

Extract the JSON parse + validate logic into `_parse_mapping(raw_text: str) -> Mapping`
so both backends share it.

### config.py changes

Add `agent_backend: str = "sdk"` to `TextreadConfig` and `"agent_backend"` to
`_KNOWN_FIELDS`. Validate on load — if value is not `sdk` or `cli`, warn and default
to `sdk`.

### cli.py changes

Add `--via-cli` flag to both `read_cmd` and `remap_cmd`. Compute effective backend:

```python
@click.option("--via-cli", is_flag=True, default=False,
              help="Use claude CLI backend instead of Anthropic SDK.")

# in read_cmd / remap_cmd body, after no-agent check:
if via_cli and no_agent:
    click.echo("[ERROR] --via-cli and --no-agent are mutually exclusive", err=True)
    sys.exit(1)

backend = "cli" if via_cli else cfg.agent_backend
```

Pass `backend` to `agent.evaluate(url, raw, ctx, model, backend=backend)`.

## Steps

1. Update `src/textread/agent.py`:
   - Extract `_parse_mapping(raw_text: str) -> Mapping` from current evaluate().
   - Rename current evaluate body to `_evaluate_sdk()`.
   - Add `_evaluate_cli()` with subprocess call.
   - Update `evaluate()` to accept `backend: str = "sdk"` and dispatch.

2. Update `src/textread/config.py`:
   - Add `agent_backend: str = "sdk"` to `TextreadConfig`.
   - Add `"agent_backend"` to `_KNOWN_FIELDS`.
   - On load: validate `agent_backend in {"sdk", "cli"}`, warn + default to `"sdk"` if not.

3. Update `src/textread/cli.py`:
   - Add `--via-cli` flag to `read_cmd` and `remap_cmd`.
   - Mutual exclusion check with `--no-agent` (R06).
   - Compute `backend` and pass to `agent.evaluate`.

4. Update `tests/test_agent.py`:
   - `test_r01_cli_backend_calls_subprocess` — monkeypatch `subprocess.run` to return
     valid JSON; assert `evaluate(..., backend="cli")` returns correct Mapping; assert
     subprocess called with `"--system"` as one of the args (not concatenated into `-p`).
   - `test_r02_cli_backend_no_binary` — monkeypatch `shutil.which` to return None;
     assert AgentError raised with "claude binary not found".
   - `test_r03_cli_backend_nonzero_exit` — subprocess returns returncode=1; assert
     AgentError raised.
   - `test_r04_cli_backend_bad_json` — subprocess returns invalid JSON; assert AgentError.
   - `test_r05_sdk_backend_unchanged` — existing SDK tests still pass unchanged.
   - `test_r06_parse_mapping_shared` — call `_parse_mapping` directly with valid JSON;
     assert correct Mapping returned.
   - `test_r07_sanitize_strips_nulls` — call `_sanitize` with a string containing null
     bytes and CR characters; assert neither appears in the result.

5. Update `tests/test_config.py`:
   - `test_agent_backend_default` — empty config; assert `cfg.agent_backend == "sdk"`.
   - `test_agent_backend_cli` — write `agent_backend: cli`; assert loaded correctly.
   - `test_agent_backend_invalid` — write `agent_backend: invalid`; assert defaults to `"sdk"`.

6. Update `tests/test_cli.py`:
   - `test_via_cli_flag_sets_backend` — monkeypatch `agent.evaluate`; invoke
     `read --via-cli <url>`; assert called with `backend="cli"`.
   - `test_via_cli_and_no_agent_mutual_exclusion` — invoke `read --via-cli --no-agent
     <url>`; assert exit 1 and `[ERROR]` in stderr.
   - `test_via_cli_remap` — same backend dispatch check for `remap --via-cli`.

7. Run `uv run pytest tests/ -v` — all green.

8. Manual smoke tests:
   ```bash
   # CLI backend via flag (needs claude on PATH, no ANTHROPIC_API_KEY required)
   textread read https://github.com/paperworlds/textread --via-cli

   # CLI backend as default via config
   echo "agent_backend: cli" >> ~/.config/paperworlds/textread.yaml
   textread read https://example.com

   # Mutual exclusion
   textread read https://example.com --via-cli --no-agent
   # → [ERROR] --via-cli and --no-agent are mutually exclusive

   # Missing binary
   # (rename claude temporarily or test in env without it)
   # → [ERROR] claude binary not found — install Claude Code or use --no-agent
   ```

## Commit message
feat: add cli agent backend — textread read --via-cli uses claude -p (v0.1.2)
