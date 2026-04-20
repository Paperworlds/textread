default:
    @just --list

# Run the test suite
test:
    uv run pytest tests/ -v

# Run tests quietly
test-q:
    uv run pytest tests/ -q

# Install (editable) via uv tool
install:
    uv tool install -e . --force

# Show installed version
version:
    uv run textread --version
