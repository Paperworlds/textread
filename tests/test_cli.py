"""CLI integration tests using CliRunner with all modules mocked."""
from __future__ import annotations

import dataclasses

import pytest
from click.testing import CliRunner

from textread.agent import AgentError, Mapping
from textread.cli import main
from textread.fetch import FetchBlocked, FetchError


URL = "https://example.com/article"


def _make_mapping(**overrides):
    defaults = dict(
        verdict="worth_reading",
        score=85,
        reason="Relevant to your stack",
        summary="A useful article",
        key_points=["point one"],
        connects_to=["project-a"],
        tags=["python"],
    )
    defaults.update(overrides)
    return Mapping(**defaults)


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def mock_deps(monkeypatch):
    """Patch all external dependencies for CLI tests."""
    import textread.cli as cli_mod

    fetch_result = object()  # sentinel — non-None means fresh fetch
    mapping = _make_mapping()

    monkeypatch.setattr(cli_mod.fetch, "pull", lambda url, refresh=False, cache=None: fetch_result)
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "raw content")
    monkeypatch.setattr(cli_mod.cache, "write_mapping", lambda url, d, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "exists", lambda url, cfg=None: True)
    monkeypatch.setattr(cli_mod.agent, "evaluate", lambda url, raw, ctx, model: mapping)
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    return {
        "fetch_result": fetch_result,
        "mapping": mapping,
    }


# ---------------------------------------------------------------------------
# R01 — basic read prints verdict
# ---------------------------------------------------------------------------

def test_r01_read_prints_verdict(runner, mock_deps):
    result = runner.invoke(main, ["read", URL])
    assert result.exit_code == 0, result.output
    assert "WORTH_READING" in result.output
    assert "85" in result.output


# ---------------------------------------------------------------------------
# R02 — --model flag reaches agent.evaluate
# ---------------------------------------------------------------------------

def test_r02_model_flag(runner, monkeypatch):
    import textread.cli as cli_mod

    called_model = []

    def fake_evaluate(url, raw, ctx, model):
        called_model.append(model)
        return _make_mapping()

    monkeypatch.setattr(cli_mod.fetch, "pull", lambda url, refresh=False, cache=None: object())
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "text")
    monkeypatch.setattr(cli_mod.cache, "write_mapping", lambda url, d, cfg: None)
    monkeypatch.setattr(cli_mod.agent, "evaluate", fake_evaluate)
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["read", URL, "--model", "sonnet"])
    assert result.exit_code == 0, result.output
    assert called_model == ["sonnet"]


# ---------------------------------------------------------------------------
# R03 — --context flag overrides context path
# ---------------------------------------------------------------------------

def test_r03_context_flag(runner, monkeypatch, tmp_path):
    import textread.cli as cli_mod
    import yaml

    ctx_file = tmp_path / "ctx.yaml"
    ctx_file.write_text(yaml.dump({"role": "tester", "stack": [], "projects": [], "filters": {}}))

    loaded_roles = []

    def fake_evaluate(url, raw, ctx, model):
        loaded_roles.append(ctx.role)
        return _make_mapping()

    monkeypatch.setattr(cli_mod.fetch, "pull", lambda url, refresh=False, cache=None: object())
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "text")
    monkeypatch.setattr(cli_mod.cache, "write_mapping", lambda url, d, cfg: None)
    monkeypatch.setattr(cli_mod.agent, "evaluate", fake_evaluate)
    # context.load should NOT be called when --context is used
    monkeypatch.setattr(cli_mod.context, "load", lambda: (_ for _ in ()).throw(AssertionError("context.load called")))

    result = runner.invoke(main, ["read", URL, "--context", str(ctx_file)])
    assert result.exit_code == 0, result.output
    assert loaded_roles == ["tester"]


# ---------------------------------------------------------------------------
# R04 — --refresh flag passes refresh=True to fetch.pull
# ---------------------------------------------------------------------------

def test_r04_refresh_flag(runner, monkeypatch):
    import textread.cli as cli_mod

    refresh_vals = []

    def fake_pull(url, refresh=False, cache=None):
        refresh_vals.append(refresh)
        return object()

    monkeypatch.setattr(cli_mod.fetch, "pull", fake_pull)
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "text")
    monkeypatch.setattr(cli_mod.cache, "write_mapping", lambda url, d, cfg: None)
    monkeypatch.setattr(cli_mod.agent, "evaluate", lambda url, raw, ctx, model: _make_mapping())
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["read", URL, "--refresh"])
    assert result.exit_code == 0, result.output
    assert refresh_vals == [True]


# ---------------------------------------------------------------------------
# R05 — --deep flag prints full mapping fields
# ---------------------------------------------------------------------------

def test_r05_deep_flag(runner, mock_deps):
    result = runner.invoke(main, ["read", URL, "--deep"])
    assert result.exit_code == 0, result.output
    # Full YAML should include all Mapping fields
    assert "verdict" in result.output
    assert "score" in result.output
    assert "summary" in result.output
    assert "key_points" in result.output
    assert "connects_to" in result.output
    assert "tags" in result.output


# ---------------------------------------------------------------------------
# R06 — remap with no cache entry → exit 1 + error message
# ---------------------------------------------------------------------------

def test_r06_remap_no_cache(runner, monkeypatch):
    import textread.cli as cli_mod

    monkeypatch.setattr(cli_mod.cache, "exists", lambda url, cfg=None: False)
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["remap", URL])
    assert result.exit_code == 1
    assert "[ERROR]" in result.output or "[ERROR]" in (result.output + (result.stderr if hasattr(result, "stderr") else ""))
    # Check the message appears somewhere in combined output
    assert "No cache entry" in result.output


# ---------------------------------------------------------------------------
# R07 — remap uses cached raw.md text
# ---------------------------------------------------------------------------

def test_r07_remap_uses_cached_raw(runner, monkeypatch):
    import textread.cli as cli_mod

    seen_raw = []

    def fake_evaluate(url, raw, ctx, model):
        seen_raw.append(raw)
        return _make_mapping()

    monkeypatch.setattr(cli_mod.cache, "exists", lambda url, cfg=None: True)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "cached markdown text")
    monkeypatch.setattr(cli_mod.cache, "write_mapping", lambda url, d, cfg: None)
    monkeypatch.setattr(cli_mod.agent, "evaluate", fake_evaluate)
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["remap", URL])
    assert result.exit_code == 0, result.output
    assert seen_raw == ["cached markdown text"]


# ---------------------------------------------------------------------------
# R10 — AgentError → exit 1, [ERROR] to stderr
# ---------------------------------------------------------------------------

def test_r10_agent_error_exits_1(monkeypatch):
    import textread.cli as cli_mod

    monkeypatch.setattr(cli_mod.fetch, "pull", lambda url, refresh=False, cache=None: object())
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "text")
    monkeypatch.setattr(cli_mod.agent, "evaluate", lambda url, raw, ctx, model: (_ for _ in ()).throw(AgentError("bad json")))
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = CliRunner().invoke(main, ["read", URL])
    assert result.exit_code == 1
    assert "[ERROR]" in result.output


# ---------------------------------------------------------------------------
# R11 — FetchBlocked → exit 1, [WARN] to stderr
# ---------------------------------------------------------------------------

def test_r11_fetch_blocked_exits_1(monkeypatch):
    import textread.cli as cli_mod

    def raise_blocked(url, refresh=False, cache=None):
        raise FetchBlocked(url)

    monkeypatch.setattr(cli_mod.fetch, "pull", raise_blocked)
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = CliRunner().invoke(main, ["read", URL])
    assert result.exit_code == 1
    assert "[WARN]" in result.output


# ---------------------------------------------------------------------------
# R12 — FetchError → exit 1, [ERROR] to stderr
# ---------------------------------------------------------------------------

def test_r12_fetch_error_exits_1(monkeypatch):
    import textread.cli as cli_mod

    def raise_error(url, refresh=False, cache=None):
        raise FetchError("connection timeout")

    monkeypatch.setattr(cli_mod.fetch, "pull", raise_error)
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = CliRunner().invoke(main, ["read", URL])
    assert result.exit_code == 1
    assert "[ERROR]" in result.output
    assert "Fetch failed" in result.output


# ---------------------------------------------------------------------------
# R01 (009) — --no-agent flag skips agent call
# ---------------------------------------------------------------------------

def test_r01_no_agent_flag_skips_agent(runner, monkeypatch):
    """With --no-agent, agent.evaluate should NOT be called."""
    import textread.cli as cli_mod

    agent_called = []

    def fake_evaluate(url, raw, ctx, model):
        agent_called.append(True)
        return _make_mapping()

    monkeypatch.setattr(cli_mod.fetch, "pull", lambda url, refresh=False, cache=None: object())
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "text")
    monkeypatch.setattr(cli_mod.agent, "evaluate", fake_evaluate)
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["read", URL, "--no-agent"])
    assert result.exit_code == 0, result.output
    assert "[CACHED]" in result.output
    assert agent_called == []  # agent.evaluate was NOT called


# ---------------------------------------------------------------------------
# R02 (009) — agent_enabled: false in config skips agent call
# ---------------------------------------------------------------------------

def test_r02_config_agent_disabled_skips_agent(runner, monkeypatch):
    """With agent_enabled: false in config, agent.evaluate should NOT be called."""
    import textread.cli as cli_mod
    from textread.config import TextreadConfig

    agent_called = []

    def fake_evaluate(url, raw, ctx, model):
        agent_called.append(True)
        return _make_mapping()

    monkeypatch.setattr(cli_mod.fetch, "pull", lambda url, refresh=False, cache=None: object())
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "text")
    monkeypatch.setattr(cli_mod.agent, "evaluate", fake_evaluate)
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())
    monkeypatch.setattr(cli_mod, "load_config", lambda: TextreadConfig(agent_enabled=False))

    result = runner.invoke(main, ["read", URL])
    assert result.exit_code == 0, result.output
    assert "[CACHED]" in result.output
    assert agent_called == []  # agent.evaluate was NOT called


# ---------------------------------------------------------------------------
# R03 (009) — --no-agent ignores --model flag
# ---------------------------------------------------------------------------

def test_r03_no_agent_ignores_model(runner, monkeypatch):
    """With --no-agent, --model flag is ignored and no error occurs."""
    import textread.cli as cli_mod

    agent_called = []

    def fake_evaluate(url, raw, ctx, model):
        agent_called.append(model)
        return _make_mapping()

    monkeypatch.setattr(cli_mod.fetch, "pull", lambda url, refresh=False, cache=None: object())
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "text")
    monkeypatch.setattr(cli_mod.agent, "evaluate", fake_evaluate)
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["read", URL, "--no-agent", "--model", "sonnet"])
    assert result.exit_code == 0, result.output
    assert "[CACHED]" in result.output
    assert agent_called == []  # agent.evaluate was NOT called


# ---------------------------------------------------------------------------
# R04 (009) — --no-agent with cached URL doesn't re-fetch
# ---------------------------------------------------------------------------

def test_r04_no_agent_cache_hit(runner, monkeypatch):
    """With --no-agent and cached content, fetch.pull is still called but cache is used."""
    import textread.cli as cli_mod

    fetch_called = []

    def fake_pull(url, refresh=False, cache=None):
        fetch_called.append(refresh)
        return None  # No new content (cache hit)

    monkeypatch.setattr(cli_mod.fetch, "pull", fake_pull)
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "cached text")
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["read", URL, "--no-agent"])
    assert result.exit_code == 0, result.output
    assert "[CACHED]" in result.output
    assert fetch_called == [False]  # fetch was called with refresh=False


# ---------------------------------------------------------------------------
# R05 (009) — remap with --no-agent errors
# ---------------------------------------------------------------------------

def test_r05_remap_no_agent_errors(runner, monkeypatch):
    """remap --no-agent should exit 1 with [ERROR] message."""
    import textread.cli as cli_mod

    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["remap", URL, "--no-agent"])
    assert result.exit_code == 1
    assert "[ERROR]" in result.output
    assert "--no-agent has no effect on remap" in result.output
