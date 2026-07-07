default:
    @just --list

# Run the test suite
test:
    uv run pytest tests/ -v

# Run tests quietly
test-q:
    uv run pytest tests/ -q

# Install (editable) via uv tool, with the profiles extra (textaccounts) for full --profile support
install:
    uv tool install -e . --force --with textaccounts

# Install without textaccounts (slim — --profile will error if used)
install-slim:
    uv tool install -e . --force

# Show installed version
version:
    uv run textread --version
