import dataclasses
from pathlib import Path

import pytest
import yaml

import textread.config as config_mod
from textread.config import TextreadConfig


def _write_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data))


def test_r01_load_existing(tmp_path, monkeypatch):
    cfg_file = tmp_path / "textread.yaml"
    _write_config(cfg_file, {"cache_root": "/tmp/cache", "default_model": "opus"})
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", cfg_file)
    cfg = config_mod.load()
    assert cfg.cache_root == "/tmp/cache"
    assert cfg.default_model == "opus"
    assert cfg.context_path == TextreadConfig().context_path  # default


def test_r02_load_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", tmp_path / "nonexistent.yaml")
    cfg = config_mod.load()
    assert cfg == TextreadConfig()


def test_r03_save_round_trip(tmp_path, monkeypatch):
    cfg_file = tmp_path / "textread.yaml"
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", cfg_file)
    original = TextreadConfig(cache_root="/my/cache", default_model="sonnet")
    config_mod.save(original)
    assert cfg_file.exists()
    reloaded = config_mod.load()
    assert reloaded == original


def test_r09_unknown_keys_ignored(tmp_path, monkeypatch):
    cfg_file = tmp_path / "textread.yaml"
    _write_config(cfg_file, {"cache_root": "/x", "future_flag": True, "unknown": "value"})
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", cfg_file)
    cfg = config_mod.load()
    assert cfg.cache_root == "/x"
    assert not hasattr(cfg, "future_flag")


def test_r06_agent_enabled_default(tmp_path, monkeypatch):
    """Agent is enabled by default."""
    cfg_file = tmp_path / "textread.yaml"
    _write_config(cfg_file, {})
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", cfg_file)
    cfg = config_mod.load()
    assert cfg.agent_enabled is True


def test_agent_enabled_false(tmp_path, monkeypatch):
    """agent_enabled: false is parsed correctly."""
    cfg_file = tmp_path / "textread.yaml"
    _write_config(cfg_file, {"agent_enabled": False})
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", cfg_file)
    cfg = config_mod.load()
    assert cfg.agent_enabled is False


# ---------------------------------------------------------------------------
# 010 — agent_backend config field
# ---------------------------------------------------------------------------

def test_agent_backend_default(tmp_path, monkeypatch):
    """Empty config defaults agent_backend to 'sdk'."""
    cfg_file = tmp_path / "textread.yaml"
    _write_config(cfg_file, {})
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", cfg_file)
    cfg = config_mod.load()
    assert cfg.agent_backend == "sdk"


def test_agent_backend_cli(tmp_path, monkeypatch):
    """agent_backend: cli is loaded correctly."""
    cfg_file = tmp_path / "textread.yaml"
    _write_config(cfg_file, {"agent_backend": "cli"})
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", cfg_file)
    cfg = config_mod.load()
    assert cfg.agent_backend == "cli"


def test_agent_backend_invalid(tmp_path, monkeypatch, capsys):
    """Invalid agent_backend value warns and defaults to 'sdk'."""
    cfg_file = tmp_path / "textread.yaml"
    _write_config(cfg_file, {"agent_backend": "invalid"})
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", cfg_file)
    cfg = config_mod.load()
    assert cfg.agent_backend == "sdk"
    captured = capsys.readouterr()
    assert "[WARN]" in captured.out


# ---------------------------------------------------------------------------
# 011 — default_profile config field
# ---------------------------------------------------------------------------

def test_default_profile_is_default(tmp_path, monkeypatch):
    """Empty config defaults default_profile to 'default' (the textaccounts default profile)."""
    cfg_file = tmp_path / "textread.yaml"
    _write_config(cfg_file, {})
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", cfg_file)
    cfg = config_mod.load()
    assert cfg.default_profile == "default"


def test_default_profile_set(tmp_path, monkeypatch):
    """default_profile: personal is loaded correctly."""
    cfg_file = tmp_path / "textread.yaml"
    _write_config(cfg_file, {"default_profile": "personal"})
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", cfg_file)
    cfg = config_mod.load()
    assert cfg.default_profile == "personal"


# ---------------------------------------------------------------------------
# 012 — pdf_backend config field
# ---------------------------------------------------------------------------

def test_pdf_backend_default(tmp_path, monkeypatch):
    """Empty config defaults pdf_backend to 'native'."""
    cfg_file = tmp_path / "textread.yaml"
    _write_config(cfg_file, {})
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", cfg_file)
    cfg = config_mod.load()
    assert cfg.pdf_backend == "native"


def test_pdf_backend_marker(tmp_path, monkeypatch):
    """pdf_backend: marker is loaded correctly."""
    cfg_file = tmp_path / "textread.yaml"
    _write_config(cfg_file, {"pdf_backend": "marker"})
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", cfg_file)
    cfg = config_mod.load()
    assert cfg.pdf_backend == "marker"


def test_pdf_backend_invalid(tmp_path, monkeypatch, capsys):
    """Invalid pdf_backend warns and defaults to 'native'."""
    cfg_file = tmp_path / "textread.yaml"
    _write_config(cfg_file, {"pdf_backend": "turbo"})
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", cfg_file)
    cfg = config_mod.load()
    assert cfg.pdf_backend == "native"
    captured = capsys.readouterr()
    assert "[WARN]" in captured.out
