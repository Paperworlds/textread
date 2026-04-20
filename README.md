# textread

Context-aware link reader. Provide a URL; get a relevance verdict and context-lensed summary back. Powered by Claude Haiku.

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

```bash
# Read a URL — fetch, cache, evaluate, print verdict
textread read https://example.com/article

# Save the read to your reading log
textread read https://example.com/article --save

# Re-evaluate a cached URL with fresh context
textread remap https://example.com/article

# Use Claude Code's auth instead of an API key
textread read https://example.com/article --via-cli

# Skip the agent — just fetch and cache
textread read https://example.com/article --no-agent
```

## Configuration

Config lives at `~/.config/paperworlds/textread.yaml`:

```yaml
default_model: haiku          # haiku | sonnet | opus
agent_enabled: true           # set false to default to --no-agent
agent_backend: sdk            # sdk | cli
default_profile: personal     # textaccounts profile for cli backend
```

Context (role, stack, projects) lives at `~/.config/paperworlds/read-context.yaml`.

## How it works

`textread read` fetches the URL, stores the raw content and a cleaned markdown version in a local cache, then passes that markdown to Claude with your context. Claude returns a structured verdict (relevant/skip/blocked), a score, a reason, and a summary lens tailored to your role and current projects.

The `--via-cli` flag shells out to `claude -p` instead of calling the Anthropic SDK directly — same auth Claude Code uses, no separate API key required.

## Roadmap

- [ ] `textread convert` — convert any cached entry to a different format
- [ ] Batch mode — read a list of URLs from a file
- [ ] `textmap` bridge — feed reading log into a knowledge graph
- [ ] Suppress nltk warning without requiring the `nlp` extra

## Part of Paperworlds

textread is part of [Paperworlds](https://github.com/paperworlds) — an open org building tools and games around AI agents and text interfaces.

## License

Elastic License 2.0
