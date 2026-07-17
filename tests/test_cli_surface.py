from pathlib import Path

from docgen.context.cli_surface import (
    cli_surface_text,
    detect_console_scripts,
    introspect_cli,
    public_api_symbols,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_detect_console_scripts_finds_docgen():
    scripts = detect_console_scripts(REPO_ROOT)
    assert ("docgen", "docgen.cli:app") in scripts


def test_introspect_cli_real_commands():
    text = introspect_cli("docgen.cli:app", "docgen")
    assert "docgen generate" in text
    assert "docgen serve" in text
    assert "docgen refine" in text
    # The template values are NOT standalone commands.
    assert "docgen readme" not in text
    assert "docgen wiki" not in text
    assert "docgen manual" not in text
    # Real options are surfaced.
    assert "--template" in text


def test_public_api_grounded():
    api = public_api_symbols(REPO_ROOT)
    joined = "\n".join(api)
    # Fabricated symbols from the hallucinated docs must never appear.
    assert "generate_wiki" not in joined
    assert "collect_project_context" not in joined
    # Real public API is present.
    assert any("GenerationEngine" in s for s in api)
    assert any("ContextCollector" in s for s in api)


def test_cli_surface_text_includes_commands_and_api():
    text = cli_surface_text(REPO_ROOT)
    assert "### Commands (`docgen`)" in text
    assert "### Python API (public symbols)" in text
    assert "docgen generate" in text


def test_cli_surface_text_empty_without_project(tmp_path):
    assert cli_surface_text(tmp_path) == ""
