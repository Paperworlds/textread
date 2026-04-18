# textread — Claude Instructions

## Project
Context-aware link reader powered by Claude Haiku. Reads URLs and produces relevance verdicts and context-lensed summaries.

## Running
- `uv sync` — install dependencies
- `uv run textread --help` — show CLI help
- `uv run pytest tests/ -v` — run test suite

## Git Rules
- You CAN commit directly — use `git -c commit.gpgsign=false commit`
- Commit after each logical unit of work
- Push after all commits

## Testing
- `uv run pytest` runs the test suite
- Use `tmp_path` fixtures for temporary file operations
- Do NOT write to real `~/.textread` in tests
- Regression tests are mandatory for bug fixes
- Tests must be fast: complete in milliseconds, not seconds

## Forums
Before starting work, run `textforums list --tag textread --status open` and check for open threads relevant to your task. Post a thread tagged `textread` if you hit a cross-repo blocker.
