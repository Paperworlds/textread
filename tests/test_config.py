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
