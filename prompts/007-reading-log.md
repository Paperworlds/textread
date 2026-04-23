---
id: '007'
title: Reading log and --save flag
repo: textread
model: haiku
budget_usd: 0.75
phase: textread
depends_on: ['006']
---

# 007 — Reading log and --save flag

## Requirements

- R01: WHEN `textread read <url> --save` is run and the agent returns a mapping,
  THE SYSTEM SHALL append one entry to `~/.textread/log.yaml`.
- R02: WHEN appending to `log.yaml`, THE SYSTEM SHALL write the entry as a YAML
  mapping with keys: `date` (ISO 8601 UTC date), `url`, `verdict`, `score`, `tags`,
  and `mapping_path` (absolute path to the cache `mapping.yaml`).
- R03: WHEN `log.yaml` does not exist, THE SYSTEM SHALL create it with the entry as
  a single-item YAML list.
- R04: WHEN `log.yaml` already exists, THE SYSTEM SHALL append to the list without
  modifying existing entries.
- R05: WHEN `log.yaml` is read by a YAML parser, THE SYSTEM SHALL be a valid YAML
  list of mappings.
- R06: WHEN `--save` is not passed, THE SYSTEM SHALL NOT write or modify `log.yaml`.

## Design

### overview

The reading log is a flat YAML list at `~/.textread/log.yaml`. It is intentionally
simple and human-editable. Shape is kept graph-compatible for the future textmap
integration: each entry has enough to reconstruct a node (url, verdict, tags, path
to full mapping). No deduplication — if the user reads the same URL twice with --save,
two entries appear. The log path is fixed (not configurable in v1).

### modules

- `src/textread/log.py` — New file. `append_entry(url, mapping, cache_path)`.
- `src/textread/cli.py` — Modified. Activate the `--save` body in `read` command to
  call `log.append_entry(...)`.
- `tests/test_log.py` — New file.

### data_structures

```yaml
# ~/.textread/log.yaml — list of entries
- date: "2026-04-18"
  url: "https://example.com/article"
  verdict: "worth_reading"
  score: 87
  tags:
    - python
    - mcp
  mapping_path: "/Users/paulie/.textread/cache/article-a1b2c3/mapping.yaml"
```

### sequence

append_flow:
  1. `log_path = Path("~/.textread/log.yaml").expanduser()`.
  2. Load existing entries: if file exists, `yaml.safe_load` → list; else `[]`.
  3. Build entry dict from `url`, `mapping`, `cache_path` per schema.
  4. Append entry to list.
  5. `log_path.parent.mkdir(parents=True, exist_ok=True)`.
  6. Write full list back with `yaml.dump(entries, ...)`.

### degradation

If the existing `log.yaml` cannot be parsed (corrupt YAML), print
`[WARN] log.yaml is malformed — creating a fresh log` and start a new list with
just the current entry. Do not abort the read command.

## Steps

1. Create `src/textread/log.py`:
   - `LOG_PATH = Path("~/.textread/log.yaml")`
   - `append_entry(url: str, mapping: Mapping, cache_path: Path, log_path: Path | None = None) -> None`
     per `sequence.append_flow` including degradation handling. When `log_path` is None,
     use `LOG_PATH`. The optional override exists solely for test isolation — tests must
     NOT write to `~/.textread/log.yaml`.

2. Update `src/textread/cli.py`:
   - In the `read` command, after `cache.write_mapping(...)`, add:
     ```python
     if save:
         from textread.log import append_entry
         append_entry(url, mapping, cache.path(url, cfg))
     ```
   - The `--save` flag is already declared (stub from prompt 006) — remove the TODO
     and activate this body.

3. Create `tests/test_log.py`:
   - All `append_entry` calls pass `log_path=tmp_path / "log.yaml"` — never write to
     the real `~/.textread/log.yaml`.
   - `test_r01_r02_appends_entry` — call `append_entry` with a fake Mapping, cache_path,
     and `log_path=tmp_path/"log.yaml"`; assert file contains one entry with all required keys.
   - `test_r03_creates_file_if_missing` — `log.yaml` absent; call `append_entry`;
     assert file is created as a valid YAML list.
   - `test_r04_appends_without_overwriting` — write a log with one entry; call
     `append_entry` again; assert two entries in file.
   - `test_r05_valid_yaml_list` — after two appends, `yaml.safe_load` returns a list.
   - `test_r06_no_save_flag_skips_log` — monkeypatch `log.LOG_PATH` to `tmp_path/"log.yaml"`;
     invoke `textread read <url>` without `--save` (mock fetch+agent); assert file not created.
   - `test_degradation_corrupt_yaml` — write `"not: valid: yaml: ["` to log path;
     call `append_entry` with same `log_path`; assert file is valid YAML with one entry afterward.

4. Run `uv run pytest tests/test_log.py -v` — all green.

## Commit message
feat: add reading log and --save flag (v0.7.0)
