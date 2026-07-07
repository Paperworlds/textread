---
id: '008'
title: Publish to GitHub
repo: textread
model: haiku
budget_usd: 0.25
phase: textread
depends_on: ['007']
---

# 008 — Publish to GitHub

## Requirements

- R01: WHEN this prompt is run, THE SYSTEM SHALL verify `uv run pytest tests/ -v`
  passes with zero failures before any publish step.
- R02: WHEN the remote `paperworlds/textread` does not yet exist, THE SYSTEM SHALL
  create it as a public repo via `gh repo create`.
- R03: WHEN the remote exists, THE SYSTEM SHALL push all commits on `main` to it.
- R04: WHEN publish is complete, THE SYSTEM SHALL print the GitHub repo URL to stdout.

## Design

### overview

This is a shell-only prompt — no new modules, no code edits. Steps are sequential
and each must succeed before the next runs. The LICENSE file already carries the
Elastic License 2.0 text, so `--license` does not need to be passed to `gh repo create`
(it reads the file in the repo).

### sequence

publish_flow:
  1. `uv run pytest tests/ -v` — must be zero failures. If any fail, STOP and report.
  2. `gh repo create paperworlds/textread --public --source=. --remote=origin --push`
     — creates repo, sets remote, and pushes in one command. If this fails because
     the remote already exists, fall through to step 3.
  3. (if remote already existed): `git push -u origin main`.
  4. Print: `Published: https://github.com/paperworlds/textread`.

### degradation

If `gh` is not installed or not authenticated, print:
`[ERROR] gh CLI not available or not authenticated — publish manually`.
Do not abort other steps that could still run.

## Steps

1. Run `uv run pytest tests/ -v`. If any tests fail, STOP — do not proceed. List the
   failures in the progress log and set state to BLOCKED.

2. Confirm `git status` is clean (no uncommitted changes). If dirty, commit with
   `git -c commit.gpgsign=false commit -am "chore: pre-publish cleanup"`.

3. Run:
   ```bash
   gh repo create paperworlds/textread \
     --public \
     --description "Context-aware link reader. URL in, relevance verdict + context-lensed summary out." \
     --source=. \
     --remote=origin \
     --push
   ```
   If the repo already exists and the above fails, run:
   ```bash
   git remote add origin https://github.com/paperworlds/textread.git 2>/dev/null || true
   git push -u origin main
   ```

4. Print: `Published: https://github.com/paperworlds/textread`

## Commit message
(no new commit — this prompt only publishes existing commits)
