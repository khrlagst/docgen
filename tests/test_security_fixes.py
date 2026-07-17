from pathlib import Path

import pytest
from typer.testing import CliRunner

from docgen.cli import app, ensure_gitignore
from docgen.config import (
    load_config,
    project_config_path,
    save_config,
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def project(tmp_path: Path, monkeypatch):
    """A git project whose cwd is set to a subdir so `config set` writes
    project-local .docgen/config.toml."""
    proj = tmp_path / "myproj"
    proj.mkdir()
    # Minimal git repo so .gitignore edits are realistic.
    (proj / ".git").mkdir()
    monkeypatch.chdir(proj)
    return proj


def test_config_set_secret_ensures_gitignore(project, runner):
    """Fix #1: writing a secret via `config set` must add .docgen/ to the
    project .gitignore so the key can never be committed, even if `init`
    was never run first."""
    result = runner.invoke(
        app, ["config", "set", "llm.api_key", "sk-super-secret-value"]
    )
    assert result.exit_code == 0, result.output

    cfg_path = project_config_path(project)
    assert cfg_path.exists()
    saved = load_config(cfg_path)
    assert saved["llm"]["api_key"] == "sk-super-secret-value"

    gitignore = project / ".gitignore"
    assert gitignore.exists()
    assert ".docgen/" in gitignore.read_text()
    # Idempotent: a second set does not duplicate the marker.
    result2 = runner.invoke(app, ["config", "set", "llm.provider", "openai"])
    assert result2.exit_code == 0, result2.output
    assert gitignore.read_text().count(".docgen/") == 1


def test_config_set_secret_masks_value_in_output(project, runner):
    """The CLI output for a secret `set` should show only a masked form."""
    result = runner.invoke(
        app, ["config", "set", "llm.api_key", "sk-super-secret-value"]
    )
    assert result.exit_code == 0, result.output
    assert "****alue" in result.output
    assert "sk-super-secret-value" not in result.output
    assert "****" in result.output


def test_config_show_masks_secret_consistently(project, runner):
    """Fix #4: `config show` masks secrets as prefix****last4, matching
    `config validate`."""
    save_config({"llm": {"api_key": "abcd1234efgh5678"}}, project_config_path(project))
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert "abcd****5678" in result.output
    assert "abcd1234efgh5678" not in result.output


def test_serve_binds_localhost(tmp_path: Path, monkeypatch):
    """Fix #2: the preview server must bind to 127.0.0.1, never 0.0.0.0."""
    from docgen.cli import _build_preview_server

    docs = tmp_path / "docs"
    docs.mkdir()
    server = _build_preview_server(docs, 8731)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()
