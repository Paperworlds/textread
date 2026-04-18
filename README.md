# textread

Context-aware link reader. Provide a URL; get a relevance verdict and context-lensed summary back. Powered by Claude Haiku.

## Usage

```bash
# Read and summarize a URL
uv run textread read https://example.com/article

# Save the summary to a file
uv run textread read https://example.com/article --save summary.md

# Remap context for specialized domain
uv run textread read https://example.com/article --context "machine learning"
```

## License

Elastic License 2.0
