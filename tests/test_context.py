import dataclasses
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

import textread.config as config_mod
import textread.context as context_mod
from textread.context import ReadContext, Project, context_group


def _patch_context_path(monkeypatch, path: Path) -> None:
    """Patch both config and context modules so context_path resolves to path."""
    from textread.config import TextreadConfig
    fake_cfg = TextreadConfig(context_path=str(path))
    monkeypatch.setattr(context_mod, "_context_path", lambda: path)


def test_r04_load_existing(tmp_path, monkeypatch):
    ctx_file = tmp_path / "read-context.yaml"
    ctx_file.write_text(yaml.dump({
        "role": "developer",
        "stack": ["python", "click"],
        "projects": [{"name": "myproject", "summary": "cool", "current": ["task1"]}],
        "filters": {"downweight": ["crypto"]},
    }))
    monkeypatch.setattr(context_mod, "_context_path", lambda: ctx_file)
    ctx = context_mod.load()
    assert ctx.role == "developer"
    assert ctx.stack == ["python", "click"]
    assert len(ctx.projects) == 1
    assert ctx.projects[0].name == "myproject"
    assert ctx.projects[0].current == ["task1"]
    assert ctx.filters == {"downweight": ["crypto"]}


def test_r05_load_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(context_mod, "_context_path", lambda: tmp_path / "nonexistent.yaml")
    ctx = context_mod.load()
    assert ctx == ReadContext()


def test_r06_save_creates_dirs(tmp_path, monkeypatch):
    nested = tmp_path / "a" / "b" / "context.yaml"
    monkeypatch.setattr(context_mod, "_context_path", lambda: nested)
    ctx = ReadContext(role="tester", stack=["pytest"])
    context_mod.save(ctx)
    assert nested.exists()
    data = yaml.safe_load(nested.read_text())
    assert data["role"] == "tester"


def test_r07_context_show(tmp_path, monkeypatch):
    ctx_file = tmp_path / "read-context.yaml"
    ctx_file.write_text(yaml.dump({"role": "engineer", "stack": ["go"]}))
    monkeypatch.setattr(context_mod, "_context_path", lambda: ctx_file)
    runner = CliRunner()
    result = runner.invoke(context_group, ["show"])
    assert result.exit_code == 0
    assert "engineer" in result.output


def test_r09_malformed_yaml(tmp_path, monkeypatch, capsys):
    ctx_file = tmp_path / "read-context.yaml"
    ctx_file.write_text("{ invalid: yaml: [broken")
    monkeypatch.setattr(context_mod, "_context_path", lambda: ctx_file)
    ctx = context_mod.load()
    assert ctx == ReadContext()
