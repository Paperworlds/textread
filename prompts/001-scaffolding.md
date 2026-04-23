---
id: '001'
title: Repo scaffolding
repo: textread
model: haiku
budget_usd: 0.50
phase: textread
depends_on: []
---

# 001 — Repo scaffolding

## Requirements

- R01: WHEN the repo is initialised, THE SYSTEM SHALL have a `pyproject.toml` declaring
  `project.name = "textread"`, `requires-python = ">=3.13"`, and dependencies
  `click`, `pyyaml`, `anthropic`, `newspaper4k`, `httpx`.
- R02: WHEN `uv run textread --help` is run, THE SYSTEM SHALL print a Click group help
  message without error.
- R03: WHEN the repo root is inspected, THE SYSTEM SHALL contain `LICENSE` with the
  Elastic License 2.0 text.
- R04: WHEN the repo root is inspected, THE SYSTEM SHALL contain `CLAUDE.md` covering
  project description, running instructions, git rules, and testing guidelines.
- R05: WHEN the repo root is inspected, THE SYSTEM SHALL contain `.gitignore` including
  Python defaults and `.textread/`.
- R06: WHEN the repo root is inspected, THE SYSTEM SHALL contain `README.md` with a
  one-paragraph description and a minimal usage example.

## Design

### overview

Bootstrap the uv-managed Python package. All source lives under `src/textread/`.
The entry point is `textread` mapped to `textread.cli:main`. The package version
starts at `0.1.0`. No logic beyond a placeholder Click group is written here —
subsequent prompts fill in the modules.

### modules

- `pyproject.toml` — project metadata, dependencies, entry points, hatchling build backend.
- `src/textread/__init__.py` — `__version__ = "0.1.0"` only.
- `src/textread/cli.py` — bare `@click.group()` named `main`, no subcommands yet.
- `CLAUDE.md` — agent conventions for this repo.
- `README.md` — pitch + quickstart.
- `LICENSE` — Elastic License 2.0 (full text, not a stub).
- `.gitignore` — standard Python + `.textread/` + `logs/` + `reports/`.

### pyproject_shape

```toml
[project]
name = "textread"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "anthropic>=0.25",
    "click>=8.1",
    "httpx>=0.27",
    "newspaper4k>=0.9",
    "pyyaml>=6.0",
]

[project.scripts]
textread = "textread.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/textread"]
```

### CLAUDE.md content

Mirror the textworkspace CLAUDE.md style:
- ## Project — one-paragraph description of textread
- ## Running — `uv sync`, `uv run textread --help`, `uv run pytest tests/ -v`
- ## Git Rules — `git -c commit.gpgsign=false commit`, commit per logical unit, push after
- ## Testing — `uv run pytest`, `tmp_path` fixtures, no real `~/.textread` writes,
  regression tests mandatory for bug fixes

## Steps

1. If `pyproject.toml` does not exist, run `uv init --package textread` and then
   replace / edit it to match `pyproject_shape` exactly.
2. Create `src/textread/__init__.py` with `__version__ = "0.1.0"`.
3. Create `src/textread/cli.py`:
   ```python
   import click
   from textread import __version__

   @click.group()
   @click.version_option(__version__)
   def main():
       """Context-aware link reader."""
   ```
4. Create `LICENSE` — full Elastic License 2.0 text. Canonical source:
   https://www.elastic.co/licensing/elastic-license
5. Create `README.md`:
   - H1: textread
   - One paragraph: "Context-aware link reader. Provide a URL; get a relevance
     verdict and context-lensed summary back. Powered by Claude Haiku."
   - `## Usage` section with three representative commands (plain read, --save, remap).
   - `## License` — Elastic License 2.0.
6. Create `CLAUDE.md` per the content spec above.
7. Create `.gitignore` — standard Python defaults plus:
   ```
   .textread/
   logs/
   reports/
   ```
8. Run `uv sync` to verify the lock file generates cleanly.
9. Run `uv run textread --help` — must print the group help.

## Commit message
feat: scaffold textread package (v0.1.0)
