# textread

Context-aware link reader and research digest tool. Feed it URLs, PDFs, and markdown files throughout the day; ask it to synthesize everything into a structured digest when you're ready. Powered by Claude.

## Install

```bash
uv tool install git+https://github.com/paperworlds/textread
textread install          # writes shell completions for your current shell
```

Or from source:

```bash
git clone https://github.com/paperworlds/textread
cd textread
uv tool install -e . --force
```

## Usage

### Reading a single source

```bash
# Auto-detect type (URL or PDF) and evaluate
textread read https://example.com/article
textread read ~/Downloads/paper.pdf

# Explicit commands
textread url https://example.com/article
textread pdf ~/Downloads/paper.pdf --pages 1-10

# Use Claude Code's auth instead of an API key
textread read https://example.com/article --via-cli

# Just fetch and cache, skip the agent
textread read https://example.com/article --no-agent
```

### Research inbox

Collect sources during the day, synthesize them all at once.

```bash
# Add sources to the inbox (fetch + cache + queue)
textread add https://example.com/article
textread add ~/Downloads/paper.pdf
textread add ~/notes/meeting.md

# Pull bookmarks from Raindrop.io into the inbox
textread pull

# See what's queued
textread inbox

# Synthesize everything — summary per item, themes, brainstorm
textread digest --model sonnet --via-cli

# Clear the inbox after digesting
textread digest --model sonnet --via-cli --clear
```

The digest is saved to `~/.local/state/paperworlds/textread/digests/YYYY-MM-DD.md`.

While a digest is running, the items being processed are locked. New `add` and `pull` calls still work — they queue for the next digest.

### Managing digests

```bash
textread digests list              # list all digests with pending/reviewed/discarded status
textread digests show 2026-04-27   # page through a digest
textread digests review 2026-04-27 # mark as reviewed
textread digests discard 2026-04-27 # mark as discarded
```

### Other commands

```bash
# Re-evaluate a cached URL with fresh context
textread remap https://example.com/article

# Inspect and manage the local cache
textread cache list
textread cache clear
```

## Configuration

Config lives at `~/.config/paperworlds/textread.yaml`:

```yaml
default_model: haiku          # haiku | sonnet | opus
agent_enabled: true           # set false to default to --no-agent
agent_backend: sdk            # sdk | cli (claude Code's auth)
default_profile: personal     # textaccounts profile for cli backend
pdf_backend: native           # native (pymupdf4llm) | marker (planned)
```

Context (role, stack, projects) lives at `~/.config/paperworlds/read-context.yaml`.

## How it works

`textread read` fetches the source, stores the raw content and a cleaned markdown version in a local three-tier cache (`raw.html` / `raw.md` / `mapping.yaml`), then passes the markdown to Claude with your context. Claude returns a structured verdict (worth reading / skim / skip), a score, a reason, and a summary tailored to your role and current projects.

`textread add` does the same fetch-and-cache step but skips the agent and queues the source in the inbox instead. `textread digest` then reads all queued items at once and asks Claude to synthesize them into a research digest: per-item summaries, shared themes, and a brainstorm section. The digest is saved as a dated markdown file so you can review it later.

The `--via-cli` flag shells out to `claude -p` instead of calling the Anthropic SDK directly — same auth Claude Code uses, no separate API key required.

## Integrations

### Raindrop.io

Save links from your browser or phone to a Raindrop collection; `textread pull` drains it into the inbox.

**Setup:**

1. Create a free account at [raindrop.io](https://raindrop.io) and create a collection called `textread`
2. Get your API token at `app.raindrop.io/settings/integrations` → Create test token
3. Add to `~/.config/paperworlds/textread.yaml`:
   ```yaml
   raindrop_token: your-token
   raindrop_collection: textread
   raindrop_digested_collection: digested  # auto-created on first pull
   ```
4. Install the [browser extension](https://raindrop.io/download) or [Android app](https://play.google.com/store/apps/details?id=io.raindrop.raindropio)
5. Save URLs to the `textread` collection throughout the day
6. Run `textread pull` — each item is fetched, cached, queued in the inbox, and moved to your `digested` collection (auto-created if missing; use `--delete` to permanently remove instead)

If a digest crash strands items, or you want to re-ingest something already processed, `textread recover --since YYYY-MM-DD` restores items created on/after that date from both Trash and the `digested` collection back into the `textread` collection. Default is today (UTC). Run `textread pull` afterward to bring them into the inbox.

## Roadmap

- [ ] `marker` PDF backend for complex/scanned PDFs
- [ ] Google Docs → markdown via Docs API
- [ ] Browser fetch backend for JS-heavy / SPA pages
- [ ] `textmap` bridge — feed digests into a knowledge graph
- [ ] Batch `add` from a file of URLs

## Part of Paperworlds

textread is part of [Paperworlds](https://github.com/paperworlds) — an open org building tools and games around AI agents and text interfaces.

## License

Elastic License 2.0
