---
id: '002'
title: Config and context modules
repo: textread
model: sonnet
budget_usd: 1.50
phase: textread
depends_on: ['001']
---

# 002 — Config and context modules

## Requirements

- R01: WHEN `config.load()` is called and `~/.config/paperworlds/textread.yaml` exists,
  THE SYSTEM SHALL return a `TextreadConfig` dataclass populated from that file.
- R02: WHEN `config.load()` is called and the file does not exist, THE SYSTEM SHALL
  return a `TextreadConfig` with all defaults without raising an error.
- R03: WHEN `config.save(cfg)` is called, THE SYSTEM SHALL write a valid YAML file to
  `~/.config/paperworlds/textread.yaml`, creating parent directories as needed.
- R04: WHEN `context.load()` is called and the context file exists, THE SYSTEM SHALL
  return a `ReadContext` dataclass populated from that file.
- R05: WHEN `context.load()` is called and the file does not exist, THE SYSTEM SHALL
  return an empty `ReadContext` without raising an error.
- R06: WHEN `context.save(ctx)` is called, THE SYSTEM SHALL write a valid YAML file to
  the path resolved by `TextreadConfig.context_path`, creating parent directories as needed.
- R07: WHEN `textread context show` is run, THE SYSTEM SHALL print the current context
  YAML to stdout.
- R08: WHEN `textread context edit` is run, THE SYSTEM SHALL open the context file in
  `$EDITOR` (defaulting to `vi` if unset).
- R09: WHEN a config or context YAML file contains an unrecognised key, THE SYSTEM SHALL
  ignore it and load the rest without error (forward-compat).

## Design

### overview

Two thin modules: `config.py` owns the tool-level config (cache root, default model,
context path); `context.py` owns the user-level read context (role, stack, projects,
filters). Both use dataclasses and PyYAML. Neither calls Click — the CLI wiring happens
in `cli.py` in prompt 006. The `context` subcommand group is registered here as a
standalone function so 006 can import and attach it.

### modules

- `src/textread/config.py` — New file. `TextreadConfig` dataclass + `load()`/`save()`.
- `src/textread/context.py` — New file. `ReadContext` dataclass + `load()`/`save()` +
  `context_group` Click group with `show` and `edit` subcommands.
- `tests/test_config.py` — New file. Tests for config round-trip and defaults.
- `tests/test_context.py` — New file. Tests for context round-trip, missing file, edit command.

### data_structures

```python
@dataclass
class TextreadConfig:
    cache_root: str = "~/.textread/cache"
    default_model: str = "haiku"
    context_path: str = "~/.config/paperworlds/read-context.yaml"

@dataclass
class Project:
    name: str
    summary: str = ""
    current: list[str] = field(default_factory=list)

@dataclass
class ReadContext:
    role: str = ""
    stack: list[str] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    filters: dict = field(default_factory=dict)   # keys: downweight (list[str])
```

### config_schema

```yaml
# ~/.config/paperworlds/textread.yaml
cache_root: ~/.textread/cache
default_model: haiku
context_path: ~/.config/paperworlds/read-context.yaml
```

```yaml
# ~/.config/paperworlds/read-context.yaml
role: developer
stack:
  - python
  - claude-code
  - textworld
projects:
  - name: paperworlds
    summary: "Text-based multiplayer RPG + AI dev tooling stack."
    current:
      - textserve release
      - textforums rollout
filters:
  downweight:
    - crypto price action
    - nocode builders
```

### sequence

config_load:
  1. Resolve path: `Path("~/.config/paperworlds/textread.yaml").expanduser()`
  2. If not exists → return `TextreadConfig()` (all defaults).
  3. Load YAML. Extract only known fields (ignore extras, R09).
  4. Return `TextreadConfig(**known_fields)`.

context_load:
  1. Load config to find `context_path`.
  2. Expand `~` in `context_path`.
  3. If not exists → return `ReadContext()`.
  4. Parse YAML. Deserialise `projects` list into `Project` dataclasses.
  5. Return `ReadContext(...)`.

### degradation

Files may be corrupt or partially written. Wrap YAML parse in try/except; on
`yaml.YAMLError` print `[WARN] textread.yaml is malformed — using defaults` and
return the default dataclass.

## Steps

1. Create `src/textread/config.py`:
   - Define `TextreadConfig` dataclass per `data_structures`.
   - `load() -> TextreadConfig` per `sequence.config_load`.
   - `save(cfg: TextreadConfig) -> None` — `mkdir(parents=True, exist_ok=True)` then
     `yaml.dump(dataclasses.asdict(cfg), ...)`.
   - Handle `yaml.YAMLError` per degradation spec.

2. Create `src/textread/context.py`:
   - Define `Project` and `ReadContext` dataclasses per `data_structures`.
   - `load() -> ReadContext` per `sequence.context_load`.
   - `save(ctx: ReadContext) -> None` — writes to resolved `context_path`.
   - `context_group` Click group:
     - `show` — loads context, `click.echo(yaml.dump(...))`.
     - `edit` — resolve path, ensure file exists (write empty YAML if not),
       `click.edit(filename=str(path))`.

3. Create `tests/test_config.py`:
   - `test_r01_load_existing` — write a valid YAML to `tmp_path`, monkeypatch the path,
     load, assert fields match.
   - `test_r02_load_missing` — do not create the file, load, assert defaults.
   - `test_r03_save_round_trip` — save a config, reload, assert equality.
   - `test_r09_unknown_keys_ignored` — write YAML with extra key, load, assert no error.

4. Create `tests/test_context.py`:
   - `test_r04_load_existing` — write context YAML, monkeypatch, load, assert fields.
   - `test_r05_load_missing` — load with no file, assert empty `ReadContext`.
   - `test_r06_save_creates_dirs` — save to nested `tmp_path` subdir, assert file exists.
   - `test_r07_context_show` — CliRunner, invoke `context show`, assert YAML in output.
   - `test_r09_malformed_yaml` — write garbage YAML, assert load returns defaults without crash.

5. Run `uv run pytest tests/test_config.py tests/test_context.py -v` — all green.

## Commit message
feat: add config and context modules (v0.2.0)
