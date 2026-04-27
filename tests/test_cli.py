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
    monkeypatch.setattr(cli_mod.agent, "evaluate", lambda url, raw, ctx, model, **kw: mapping)
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

    def fake_evaluate(url, raw, ctx, model, **kw):
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

    def fake_evaluate(url, raw, ctx, model, **kw):
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
    monkeypatch.setattr(cli_mod.agent, "evaluate", lambda url, raw, ctx, model, **kw: _make_mapping())
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

    def fake_evaluate(url, raw, ctx, model, **kw):
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
    monkeypatch.setattr(cli_mod.agent, "evaluate", lambda url, raw, ctx, model, **kw: (_ for _ in ()).throw(AgentError("bad json")))
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

    def fake_evaluate(url, raw, ctx, model, **kw):
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

    def fake_evaluate(url, raw, ctx, model, **kw):
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

    def fake_evaluate(url, raw, ctx, model, **kw):
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


# ---------------------------------------------------------------------------
# 010 — --via-cli backend dispatch
# ---------------------------------------------------------------------------

def test_via_cli_flag_sets_backend(runner, monkeypatch):
    """--via-cli passes backend='cli' to agent.evaluate."""
    import textread.cli as cli_mod

    seen_backend = []

    def fake_evaluate(url, raw, ctx, model, **kw):
        seen_backend.append(kw.get("backend"))
        return _make_mapping()

    monkeypatch.setattr(cli_mod.fetch, "pull", lambda url, refresh=False, cache=None: object())
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "text")
    monkeypatch.setattr(cli_mod.cache, "write_mapping", lambda url, d, cfg: None)
    monkeypatch.setattr(cli_mod.agent, "evaluate", fake_evaluate)
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["read", URL, "--via-cli"])
    assert result.exit_code == 0, result.output
    assert seen_backend == ["cli"]


def test_via_cli_and_no_agent_mutual_exclusion(runner, monkeypatch):
    """--via-cli and --no-agent together should exit 1 with [ERROR]."""
    import textread.cli as cli_mod

    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["read", URL, "--via-cli", "--no-agent"])
    assert result.exit_code == 1
    assert "[ERROR]" in result.output
    assert "--via-cli and --no-agent are mutually exclusive" in result.output


def test_via_cli_remap(runner, monkeypatch):
    """remap --via-cli passes backend='cli' to agent.evaluate."""
    import textread.cli as cli_mod

    seen_backend = []

    def fake_evaluate(url, raw, ctx, model, **kw):
        seen_backend.append(kw.get("backend"))
        return _make_mapping()

    monkeypatch.setattr(cli_mod.cache, "exists", lambda url, cfg=None: True)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "cached text")
    monkeypatch.setattr(cli_mod.cache, "write_mapping", lambda url, d, cfg: None)
    monkeypatch.setattr(cli_mod.agent, "evaluate", fake_evaluate)
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["remap", URL, "--via-cli"])
    assert result.exit_code == 0, result.output
    assert seen_backend == ["cli"]


# ---------------------------------------------------------------------------
# 011 — --profile flag and default_profile config
# ---------------------------------------------------------------------------

def test_profile_flag_passed_to_agent(runner, monkeypatch):
    """--profile personal is forwarded to agent.evaluate as profile='personal'."""
    import textread.cli as cli_mod

    seen_profile = []

    def fake_evaluate(url, raw, ctx, model, **kw):
        seen_profile.append(kw.get("profile"))
        return _make_mapping()

    monkeypatch.setattr(cli_mod.fetch, "pull", lambda url, refresh=False, cache=None: object())
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "text")
    monkeypatch.setattr(cli_mod.cache, "write_mapping", lambda url, d, cfg: None)
    monkeypatch.setattr(cli_mod.agent, "evaluate", fake_evaluate)
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["read", URL, "--via-cli", "--profile", "personal"])
    assert result.exit_code == 0, result.output
    assert seen_profile == ["personal"]


def test_default_profile_from_config(runner, monkeypatch):
    """default_profile from config is used when --profile is not passed."""
    import textread.cli as cli_mod
    from textread.config import TextreadConfig

    seen_profile = []

    def fake_evaluate(url, raw, ctx, model, **kw):
        seen_profile.append(kw.get("profile"))
        return _make_mapping()

    monkeypatch.setattr(cli_mod.fetch, "pull", lambda url, refresh=False, cache=None: object())
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "text")
    monkeypatch.setattr(cli_mod.cache, "write_mapping", lambda url, d, cfg: None)
    monkeypatch.setattr(cli_mod.agent, "evaluate", fake_evaluate)
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())
    monkeypatch.setattr(cli_mod, "load_config", lambda: TextreadConfig(agent_backend="cli", default_profile="work"))

    result = runner.invoke(main, ["read", URL])
    assert result.exit_code == 0, result.output
    assert seen_profile == ["work"]


def test_profile_with_sdk_backend_warns(runner, monkeypatch):
    """--profile with sdk backend prints [WARN] and exits 0."""
    import textread.agent as agent_mod
    import textread.cli as cli_mod

    # Patch _evaluate_sdk so real evaluate() runs (and prints the [WARN]) without hitting the API
    monkeypatch.setattr(agent_mod, "_evaluate_sdk", lambda url, raw, ctx, model: _make_mapping())
    monkeypatch.setattr(cli_mod.fetch, "pull", lambda url, refresh=False, cache=None: object())
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "text")
    monkeypatch.setattr(cli_mod.cache, "write_mapping", lambda url, d, cfg: None)
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["read", URL, "--profile", "personal"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    # CliRunner with mix_stderr=True (default) merges stderr into output
    assert "[WARN]" in result.output


# ---------------------------------------------------------------------------
# 012 — url command (explicit web pipeline)
# ---------------------------------------------------------------------------

def test_url_cmd_basic(runner, mock_deps):
    """`textread url <url>` runs the same pipeline as old `read`."""
    result = runner.invoke(main, ["url", URL])
    assert result.exit_code == 0, result.output
    assert "WORTH_READING" in result.output


def test_url_cmd_no_agent(runner, monkeypatch):
    """`textread url --no-agent` skips agent and prints [CACHED]."""
    import textread.cli as cli_mod

    monkeypatch.setattr(cli_mod.fetch, "pull", lambda url, refresh=False, cache=None: object())
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "text")
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["url", URL, "--no-agent"])
    assert result.exit_code == 0, result.output
    assert "[CACHED]" in result.output


# ---------------------------------------------------------------------------
# 012 — pdf command
# ---------------------------------------------------------------------------

def test_pdf_cmd_basic(runner, monkeypatch, tmp_path):
    """`textread pdf <file>` extracts, caches, runs agent, prints verdict."""
    import textread.cli as cli_mod

    pdf_file = tmp_path / "paper.pdf"
    pdf_file.write_bytes(b"%PDF fake")

    from textread.fetch import FetchResult
    fake_result = FetchResult(
        url=pdf_file.as_uri(), final_url=pdf_file.as_uri(),
        text="# PDF content", content_type="application/pdf",
        fetched_at="2026-01-01T00:00:00Z",
    )
    monkeypatch.setattr(cli_mod.fetch, "fetch_pdf", lambda source, pages=None, backend="native": fake_result)
    monkeypatch.setattr(cli_mod.cache, "exists", lambda url, cfg=None: False)
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "# PDF content")
    monkeypatch.setattr(cli_mod.cache, "write_mapping", lambda url, d, cfg: None)
    monkeypatch.setattr(cli_mod.agent, "evaluate", lambda url, raw, ctx, model, **kw: _make_mapping())
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["pdf", str(pdf_file)])
    assert result.exit_code == 0, result.output
    assert "WORTH_READING" in result.output


def test_pdf_cmd_no_agent(runner, monkeypatch, tmp_path):
    """`textread pdf --no-agent` extracts, caches, skips agent."""
    import textread.cli as cli_mod

    pdf_file = tmp_path / "paper.pdf"
    pdf_file.write_bytes(b"%PDF fake")

    from textread.fetch import FetchResult
    fake_result = FetchResult(
        url=pdf_file.as_uri(), final_url=pdf_file.as_uri(),
        text="# PDF content", content_type="application/pdf",
        fetched_at="2026-01-01T00:00:00Z",
    )
    agent_called = []
    monkeypatch.setattr(cli_mod.fetch, "fetch_pdf", lambda source, pages=None, backend="native": fake_result)
    monkeypatch.setattr(cli_mod.cache, "exists", lambda url, cfg=None: False)
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "# PDF content")
    monkeypatch.setattr(cli_mod.agent, "evaluate", lambda *a, **kw: agent_called.append(True) or _make_mapping())
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["pdf", str(pdf_file), "--no-agent"])
    assert result.exit_code == 0, result.output
    assert "[CACHED]" in result.output
    assert agent_called == []


def test_pdf_cmd_cache_hit_skips_extraction(runner, monkeypatch, tmp_path):
    """pdf with cached entry skips fetch_pdf entirely."""
    import textread.cli as cli_mod

    pdf_file = tmp_path / "paper.pdf"
    pdf_file.write_bytes(b"%PDF fake")

    fetch_called = []
    monkeypatch.setattr(cli_mod.fetch, "fetch_pdf", lambda *a, **kw: fetch_called.append(True))
    monkeypatch.setattr(cli_mod.cache, "exists", lambda url, cfg=None: True)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "cached md")
    monkeypatch.setattr(cli_mod.cache, "write_mapping", lambda url, d, cfg: None)
    monkeypatch.setattr(cli_mod.agent, "evaluate", lambda url, raw, ctx, model, **kw: _make_mapping())
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["pdf", str(pdf_file)])
    assert result.exit_code == 0, result.output
    assert fetch_called == []


# ---------------------------------------------------------------------------
# 012 — read smart router
# ---------------------------------------------------------------------------

def test_read_routes_url(runner, mock_deps):
    """`read` with an http URL routes to url pipeline and logs [READ] url."""
    result = runner.invoke(main, ["read", URL])
    assert result.exit_code == 0, result.output
    assert "[READ] url →" in result.output
    assert "WORTH_READING" in result.output


def test_read_routes_pdf(runner, monkeypatch, tmp_path):
    """`read` with a .pdf path routes to pdf pipeline and logs [READ] pdf."""
    import textread.cli as cli_mod

    pdf_file = tmp_path / "paper.pdf"
    pdf_file.write_bytes(b"%PDF fake")

    from textread.fetch import FetchResult
    fake_result = FetchResult(
        url=pdf_file.as_uri(), final_url=pdf_file.as_uri(),
        text="# PDF", content_type="application/pdf",
        fetched_at="2026-01-01T00:00:00Z",
    )
    monkeypatch.setattr(cli_mod.fetch, "fetch_pdf", lambda source, pages=None, backend="native": fake_result)
    monkeypatch.setattr(cli_mod.cache, "exists", lambda url, cfg=None: False)
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "# PDF")
    monkeypatch.setattr(cli_mod.cache, "write_mapping", lambda url, d, cfg: None)
    monkeypatch.setattr(cli_mod.agent, "evaluate", lambda url, raw, ctx, model, **kw: _make_mapping())
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["read", str(pdf_file)])
    assert result.exit_code == 0, result.output
    assert "[READ] pdf →" in result.output
    assert "WORTH_READING" in result.output


def test_read_routes_pdf_url(runner, monkeypatch):
    """`read` with a URL ending in .pdf routes to pdf pipeline."""
    import textread.cli as cli_mod

    PDF_URL = "https://arxiv.org/pdf/2401.00001.pdf"
    from textread.fetch import FetchResult
    fake_result = FetchResult(
        url=PDF_URL, final_url=PDF_URL,
        text="# Abstract", content_type="application/pdf",
        fetched_at="2026-01-01T00:00:00Z",
    )
    monkeypatch.setattr(cli_mod.fetch, "fetch_pdf", lambda source, pages=None, backend="native": fake_result)
    monkeypatch.setattr(cli_mod.cache, "exists", lambda url, cfg=None: False)
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda url, cfg: "# Abstract")
    monkeypatch.setattr(cli_mod.cache, "write_mapping", lambda url, d, cfg: None)
    monkeypatch.setattr(cli_mod.agent, "evaluate", lambda url, raw, ctx, model, **kw: _make_mapping())
    monkeypatch.setattr(cli_mod.context, "load", lambda: cli_mod.ReadContext())

    result = runner.invoke(main, ["read", PDF_URL])
    assert result.exit_code == 0, result.output
    assert "[READ] pdf →" in result.output


# ---------------------------------------------------------------------------
# 013 — add command
# ---------------------------------------------------------------------------

@pytest.fixture()
def patch_inbox(monkeypatch, tmp_path):
    """Redirect inbox to tmp files so tests don't touch ~/.local/state."""
    import textread.inbox as inbox_mod
    monkeypatch.setattr(inbox_mod, "INBOX_PATH", tmp_path / "inbox.jsonl")
    monkeypatch.setattr(inbox_mod, "PROCESSING_PATH", tmp_path / "inbox.processing.jsonl")
    monkeypatch.setattr(inbox_mod, "LOCK_PATH", tmp_path / "inbox.lock")
    return inbox_mod


def test_add_url(runner, monkeypatch, patch_inbox):
    """`textread add <url>` fetches, caches, and appends to inbox."""
    import textread.cli as cli_mod

    monkeypatch.setattr(cli_mod.fetch, "pull", lambda url, cache=None, refresh=False: object())
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)
    monkeypatch.setattr(cli_mod.cache, "exists", lambda url, cfg=None: False)

    result = runner.invoke(main, ["add", URL])
    assert result.exit_code == 0, result.output
    assert "[INBOX] added (url)" in result.output
    assert len(patch_inbox.list_entries()) == 1
    assert patch_inbox.list_entries()[0].type == "url"


def test_add_pdf(runner, monkeypatch, tmp_path, patch_inbox):
    """`textread add <file.pdf>` extracts, caches, and appends to inbox."""
    import textread.cli as cli_mod
    from textread.fetch import FetchResult

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF fake")
    fake = FetchResult(url=pdf.as_uri(), final_url=pdf.as_uri(),
                       text="# Content", content_type="application/pdf",
                       fetched_at="2026-01-01T00:00:00Z")
    monkeypatch.setattr(cli_mod.fetch, "fetch_pdf", lambda source, pages=None, backend="native": fake)
    monkeypatch.setattr(cli_mod.cache, "exists", lambda url, cfg=None: False)
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: None)

    result = runner.invoke(main, ["add", str(pdf)])
    assert result.exit_code == 0, result.output
    assert "[INBOX] added (pdf)" in result.output
    assert patch_inbox.list_entries()[0].type == "pdf"


def test_add_md(runner, monkeypatch, tmp_path, patch_inbox):
    """`textread add <file.md>` reads, caches, and appends to inbox."""
    import textread.cli as cli_mod

    md = tmp_path / "notes.md"
    md.write_text("# Hello\nSome content.", encoding="utf-8")
    cached = []
    monkeypatch.setattr(cli_mod.cache, "exists", lambda url, cfg=None: False)
    monkeypatch.setattr(cli_mod.cache, "put", lambda url, result, cfg: cached.append(result))

    result = runner.invoke(main, ["add", str(md)])
    assert result.exit_code == 0, result.output
    assert "[INBOX] added (md)" in result.output
    e = patch_inbox.list_entries()[0]
    assert e.type == "md"
    assert e.title == "notes"
    assert cached[0].content_type == "text/markdown"


def test_add_md_missing_file_exits_1(runner, monkeypatch, patch_inbox):
    """`textread add` with a non-existent .md file exits 1."""
    result = runner.invoke(main, ["add", "/nonexistent/file.md"])
    assert result.exit_code == 1
    assert "[ERROR]" in result.output


def test_add_skips_cache_if_already_cached(runner, monkeypatch, tmp_path, patch_inbox):
    """`textread add` skips fetch_pdf if cache entry already exists."""
    import textread.cli as cli_mod

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF fake")
    fetch_called = []
    monkeypatch.setattr(cli_mod.fetch, "fetch_pdf", lambda *a, **kw: fetch_called.append(True))
    monkeypatch.setattr(cli_mod.cache, "exists", lambda url, cfg=None: True)

    result = runner.invoke(main, ["add", str(pdf)])
    assert result.exit_code == 0, result.output
    assert fetch_called == []


# ---------------------------------------------------------------------------
# 013 — inbox command
# ---------------------------------------------------------------------------

def test_inbox_empty(runner, patch_inbox):
    result = runner.invoke(main, ["inbox"])
    assert result.exit_code == 0, result.output
    assert "Inbox is empty" in result.output


def test_inbox_lists_entries(runner, patch_inbox):
    patch_inbox.add("https://a.com", "url", "A", "https://a.com")
    patch_inbox.add("/doc.pdf", "pdf", "doc", "file:///doc.pdf")
    result = runner.invoke(main, ["inbox"])
    assert result.exit_code == 0, result.output
    assert "url" in result.output
    assert "pdf" in result.output
    assert "2 item(s) pending digest" in result.output


# ---------------------------------------------------------------------------
# 013 — digest command
# ---------------------------------------------------------------------------

def test_digest_empty_inbox(runner, patch_inbox):
    result = runner.invoke(main, ["digest"])
    assert result.exit_code == 0, result.output
    assert "Inbox is empty" in result.output


def test_digest_calls_agent_and_prints(runner, monkeypatch, tmp_path, patch_inbox):
    """`textread digest` collects cached content, calls agent.digest, saves file."""
    import textread.cli as cli_mod

    import textread.digests as digests_mod
    monkeypatch.setattr(digests_mod, "DIGESTS_DIR", tmp_path / "digests")
    patch_inbox.add("https://a.com", "url", "A", "https://a.com")
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda key, cfg: "content of a")
    monkeypatch.setattr(cli_mod.agent, "digest",
                        lambda items, model, backend, profile: "## Item Summaries\nFoo")

    result = runner.invoke(main, ["digest"])
    assert result.exit_code == 0, result.output
    assert "## Item Summaries" in result.output
    assert "[DIGEST] saved" in result.output
    saved = list((tmp_path / "digests").glob("*.md"))
    assert len(saved) == 1
    assert "## Sources" in saved[0].read_text()


def test_digest_clear_flag_removes_inbox(runner, monkeypatch, tmp_path, patch_inbox):
    """`textread digest --clear` clears the inbox after digest."""
    import textread.cli as cli_mod

    import textread.digests as digests_mod
    monkeypatch.setattr(digests_mod, "DIGESTS_DIR", tmp_path / "digests")
    patch_inbox.add("https://a.com", "url", "A", "https://a.com")
    monkeypatch.setattr(cli_mod.cache, "get_markdown", lambda key, cfg: "text")
    monkeypatch.setattr(cli_mod.agent, "digest",
                        lambda items, model, backend, profile: "## Done")

    result = runner.invoke(main, ["digest", "--clear"])
    assert result.exit_code == 0, result.output
    assert patch_inbox.list_entries() == []


def test_digest_skips_missing_cache(runner, monkeypatch, tmp_path, patch_inbox):
    """`textread digest` warns and skips entries with no cached content."""
    import textread.cli as cli_mod
    from textread.cache import CacheError

    import textread.digests as digests_mod
    monkeypatch.setattr(digests_mod, "DIGESTS_DIR", tmp_path / "digests")
    patch_inbox.add("https://a.com", "url", "A", "https://a.com")
    monkeypatch.setattr(cli_mod.cache, "get_markdown",
                        lambda key, cfg: (_ for _ in ()).throw(CacheError("missing")))

    result = runner.invoke(main, ["digest"])
    assert result.exit_code == 1
    assert "[WARN]" in result.output or "No cached content" in result.output


# ---------------------------------------------------------------------------
# 013 — digests list/show/review commands
# ---------------------------------------------------------------------------

@pytest.fixture()
def patch_digests(monkeypatch, tmp_path):
    import textread.digests as digests_mod
    monkeypatch.setattr(digests_mod, "DIGESTS_DIR", tmp_path / "digests")
    return digests_mod


def test_digests_list_empty(runner, patch_digests):
    result = runner.invoke(main, ["digests", "list"])
    assert result.exit_code == 0, result.output
    assert "No digests" in result.output


def test_digests_list_shows_pending(runner, patch_digests, tmp_path):
    d = tmp_path / "digests"
    d.mkdir()
    (d / "2026-04-27.md").write_text(
        "# Digest — 2026-04-27\n\n## Sources\n\n- [pdf] a.pdf\n- [url] b.com\n\n---\n\nContent\n"
    )
    result = runner.invoke(main, ["digests", "list"])
    assert result.exit_code == 0, result.output
    assert "2026-04-27" in result.output
    assert "pending" in result.output
    assert "2 source" in result.output


def test_digests_review_marks_file(runner, patch_digests, tmp_path):
    d = tmp_path / "digests"
    d.mkdir()
    (d / "2026-04-27.md").write_text("# Digest\n\n## Sources\n\n- [pdf] a.pdf\n")
    result = runner.invoke(main, ["digests", "review", "2026-04-27"])
    assert result.exit_code == 0, result.output
    assert "marked reviewed" in result.output
    assert (d / "2026-04-27.state").read_text().strip() == "reviewed"


def test_digests_list_shows_reviewed(runner, patch_digests, tmp_path):
    d = tmp_path / "digests"
    d.mkdir()
    (d / "2026-04-27.md").write_text("# Digest\n\n## Sources\n\n- [pdf] a.pdf\n")
    (d / "2026-04-27.state").write_text("reviewed\n")
    result = runner.invoke(main, ["digests", "list"])
    assert "reviewed" in result.output


def test_digests_review_missing_exits_1(runner, patch_digests):
    result = runner.invoke(main, ["digests", "review", "1999-01-01"])
    assert result.exit_code == 1
    assert "[ERROR]" in result.output


def test_digests_show_prints_content(runner, patch_digests, tmp_path):
    d = tmp_path / "digests"
    d.mkdir()
    (d / "2026-04-27.md").write_text("# Digest\n\nHello world\n")
    result = runner.invoke(main, ["digests", "show", "2026-04-27"])
    assert result.exit_code == 0, result.output
    assert "Hello world" in result.output


def test_digests_show_missing_exits_1(runner, patch_digests):
    result = runner.invoke(main, ["digests", "show", "1999-01-01"])
    assert result.exit_code == 1
    assert "[ERROR]" in result.output


def test_digests_discard(runner, patch_digests, tmp_path):
    d = tmp_path / "digests"
    d.mkdir()
    (d / "2026-04-27.md").write_text("# Digest\n\n## Sources\n\n- [pdf] a.pdf\n")
    result = runner.invoke(main, ["digests", "discard", "2026-04-27"])
    assert result.exit_code == 0, result.output
    assert "discarded" in result.output
    assert (d / "2026-04-27.state").read_text().strip() == "discarded"


def test_digests_discard_shows_in_list(runner, patch_digests, tmp_path):
    d = tmp_path / "digests"
    d.mkdir()
    (d / "2026-04-27.md").write_text("# Digest\n\n## Sources\n\n- [pdf] a.pdf\n")
    (d / "2026-04-27.state").write_text("discarded\n")
    result = runner.invoke(main, ["digests", "list"])
    assert "discarded" in result.output
