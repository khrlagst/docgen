import os
from pathlib import Path

import pytest

from docgen.config import (
    DEFAULT_CONFIG_PATH,
    load_config,
    load_merged,
    project_config_path,
    save_config,
)
from docgen.cli import ensure_gitignore


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(
        "docgen.config.DEFAULT_CONFIG_PATH",
        home / ".config" / "docgen" / "config.toml",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def test_project_config_path(isolated_home):
    proj = isolated_home / "myproj"
    assert project_config_path(proj) == proj / ".docgen" / "config.toml"


def test_load_merged_project_overrides_global(isolated_home):
    cfg_path = isolated_home / ".config" / "docgen" / "config.toml"
    global_cfg = {"llm": {"provider": "openrouter", "model": "a"}, "x": 1}
    save_config(global_cfg, cfg_path)
    proj = isolated_home / "myproj"
    proj.mkdir()
    save_config({"llm": {"model": "b"}}, project_config_path(proj))

    merged = load_merged(proj)
    assert merged["llm"]["provider"] == "openrouter"  # inherited
    assert merged["llm"]["model"] == "b"  # overridden
    assert merged["x"] == 1


def test_load_merged_without_project_returns_global(isolated_home):
    cfg_path = isolated_home / ".config" / "docgen" / "config.toml"
    save_config({"llm": {"provider": "deepseek"}}, cfg_path)
    merged = load_merged(None)
    assert merged["llm"]["provider"] == "deepseek"


def test_ensure_gitignore_appends_marker(isolated_home):
    proj = isolated_home / "myproj"
    proj.mkdir()
    ensure_gitignore(proj)
    gitignore = proj / ".gitignore"
    assert gitignore.exists()
    assert ".docgen/" in gitignore.read_text()

    # idempotent: running again does not duplicate the marker
    ensure_gitignore(proj)
    assert gitignore.read_text().count(".docgen/") == 1


def test_ensure_gitignore_preserves_existing_entries(isolated_home):
    proj = isolated_home / "myproj"
    proj.mkdir()
    (proj / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    ensure_gitignore(proj)
    text = (proj / ".gitignore").read_text()
    assert "node_modules/" in text
    assert ".docgen/" in text
