# textread — Feature Context

Repo: paperworlds/textread (public, Elastic License 2.0)

Context-aware link reader. URL or local path in → relevance verdict + context-lensed
summary out. Knows who you are and what you're building, so it can filter the signal
from the noise.

## Why

The volume of AI/dev news is overwhelming. Most articles are noise relative to what
you're actually shipping. A reader that knows your current projects can filter the
feed and surface only what connects to real work. Cheaper attention, faster validation
loops.

## Design principles

- Small surface. Sync only. Claude only at v1.
- Fetch once, map many. Raw is the archive; `mapping.yaml` is the interpretation.
- Fresh Anthropic SDK call per read — predictable cost, clean context.
- Haiku default, `--model` override. Typical read in cents, not dollars.
- `mapping.yaml` is textmap-compatible from day one (textmap doesn't ship yet, but the
  shape is designed for the bridge).

## CLI surface

```
textread <url|path>                  # fetch (cached), evaluate, print
textread <url|path> --model sonnet   # override model
textread <url|path> --context <f>    # one-off context override
textread <url|path> --refresh        # force re-fetch
textread <url|path> --save           # append to reading log
textread remap <url|path>            # re-run agent on cached raw
textread context show|edit           # manage user context file
textread cache list|path <url>|clear # cache management
textread convert <path>              # PDF/DOC → markdown, no agent
```

## Three-tier storage

```
~/.textread/cache/<slug-or-hash>/
  raw.<ext>        # original binary — fetched once, never sent to LLM
  raw.md           # cleaned markdown — what the agent actually receives
  raw.meta.json    # url, fetched_at, content-type, final-url, format
  mapping.yaml     # verdict + summary + extract — regeneratable from raw.md
```

PDFs and binary formats are converted to `raw.md` before the agent sees them.
The raw binary is archived locally for provenance; only the markdown goes to Claude.

## Agent output schema

```yaml
verdict: worth_reading | skim | skip
score: 0-100
reason: "one-line why for this user"
summary: "<=200 words, lensed through user context"
key_points: ["...", "..."]
connects_to: ["paperworlds/textserve", ...]   # matched against context projects
tags: ["mcp", "k8s", ...]
```

## User context

Stored at `~/.config/paperworlds/read-context.yaml`. Contains: role, stack, current
projects (with goals and blockers), and downweight filters. This is what makes the
verdict relevant — without it, the agent gives a generic summary; with it, the output
is lensed through what you're actually building.

## Format support (convert command)

| Format | Library |
|--------|---------|
| PDF    | pdfminer.six / pymupdf |
| DOCX   | python-docx |
| XLSX   | openpyxl |
| PPTX   | python-pptx |
| HTML   | newspaper4k (maintained fork of newspaper3k) |

## Package structure

```
src/textread/
  __init__.py    # version
  cli.py         # click group: read, remap, context, cache, convert
  fetch.py       # newspaper4k wrapper, robots.txt check, UA, cache-skip logic
  cache.py       # ~/.textread/cache/<slug>/ layout, read/write, slug generation
  agent.py       # Anthropic SDK call, prompt construction, output schema validation
  context.py     # load/save read-context.yaml
  config.py      # ~/.config/paperworlds/textread.yaml resolution
tests/
```

## Build tasks (see PLAN.yaml)

1. Scaffolding — uv package, pyproject.toml, CLAUDE.md, LICENSE
2. Config + context — load/save, round-trip tests
3. Fetch layer — newspaper4k, robots.txt, UA, cache-skip
4. Cache layer — slug+hash key, directory layout, helpers
5. Agent layer — Anthropic SDK, structured output, model aliases
6. CLI — wire fetch → cache → agent → output
7. Reading log — `--save` appends to `~/.textread/log.yaml`
8. Publish — push to paperworlds/textread, flip landing page badge

Current status: scaffolding. All prompts written. Git initialized. No Python code yet.

## Constraints

- Python ≥3.11, uv-managed
- Anthropic SDK only — no multi-provider abstraction at v1
- Sync only — no async, no background jobs
- Robots.txt must be respected
- No YouTube transcripts, no paywalled content at v1

## Future

- textmap bridge — promoted mappings become graph nodes
- Batch mode — read a file of URLs, emit ranked report
- Claude Code slash command — `/read <url>` from inside a session
- Bookmarks with 1–5 star ratings + labels → preference map feedback loop
