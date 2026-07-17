"""Tests for the interactive REPL command handling (TUI fixes)."""
import questionary

import docgen.tui as tui
from docgen.welcome import run_onboarding


def test_normalize_input_strips_docgen_prefix():
    assert tui._normalize_input("docgen config set x y") == "config set x y"
    assert tui._normalize_input("  DOCGEN  generate ") == "generate"
    assert tui._normalize_input("/config") == "config"
    assert tui._normalize_input("/docgen serve") == "serve"
    assert tui._normalize_input("  ") == ""


def test_run_typer_command_is_in_process(capsys):
    # `legal` is a real subcommand; in-process delegation must work and must
    # NOT leak a `python -m docgen` subprocess invocation.
    tui._run_typer_command("legal")
    out = capsys.readouterr().out
    assert "Terms of Service" in out
    assert "python -m" not in out


def test_run_typer_command_unknown_handled_gracefully(capsys):
    # An unknown command should be caught (UsageError) and not crash the REPL
    # or leak `python -m docgen`.
    tui._run_typer_command("definitely_not_a_real_cmd")
    out = capsys.readouterr().out
    assert "python -m" not in out


def test_run_typer_command_no_args_subcommand_shows_no_error(capsys):
    # `docgen config` (no subcommand) prints help via no_args_is_help and must
    # NOT leave a stray `Error:` line (regression: typer bundles its own
    # click, so the vendored NoArgsIsHelpError was previously uncaught).
    tui._run_typer_command("config")
    out = capsys.readouterr().out
    assert "Usage: docgen config" in out
    assert "Error:" not in out


def test_run_typer_command_bad_subcommand_shows_friendly_message(capsys):
    # A real usage error (unknown subcommand) should be shown friendly, not as
    # a raw `Error:`.
    tui._run_typer_command("config frobnicate")
    out = capsys.readouterr().out
    assert "No such command 'frobnicate'." in out
    assert "Error:" not in out


def test_usage_references_docgen_not_python_minus_m():
    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(tui.app, ["bogus"])
    assert "python -m" not in result.output
    assert "Usage: docgen" in result.output


def test_help_references_docgen_not_python_minus_m():
    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(tui.app, ["--help"])
    assert "python -m" not in result.output
    assert "Usage: docgen" in result.output


def test_repl_rejects_unknown_command(monkeypatch, capsys):
    import docgen.welcome as welcome

    monkeypatch.setattr(welcome, "is_first_run", lambda: False)

    inputs = iter(["frobnicate", "exit"])

    class FakeSession:
        def prompt(self, *args, **kwargs):
            try:
                return next(inputs)
            except StopIteration:
                raise EOFError

    monkeypatch.setattr(tui, "PromptSession", lambda *a, **k: FakeSession())

    tui._interactive_loop()

    out = capsys.readouterr().out
    assert "Unknown command" in out
    assert "frobnicate" in out


def test_repl_accepts_docgen_prefixed_command(monkeypatch, capsys):
    import docgen.welcome as welcome

    monkeypatch.setattr(welcome, "is_first_run", lambda: False)

    inputs = iter(["docgen config show", "exit"])

    class FakeSession:
        def prompt(self, *a, **k):
            try:
                return next(inputs)
            except StopIteration:
                raise EOFError

    monkeypatch.setattr(tui, "PromptSession", lambda *a, **k: FakeSession())

    tui._interactive_loop()

    out = capsys.readouterr().out
    # The `docgen`-prefixed form must NOT be treated as unknown.
    assert "Unknown command" not in out


def _run_repl_with(inputs, monkeypatch, capsys):
    import docgen.welcome as welcome

    monkeypatch.setattr(welcome, "is_first_run", lambda: False)

    stream = iter(inputs)

    class FakeSession:
        def prompt(self, *a, **k):
            try:
                return next(stream)
            except StopIteration:
                raise EOFError

    monkeypatch.setattr(tui, "PromptSession", lambda *a, **k: FakeSession())
    tui._interactive_loop()
    return capsys.readouterr().out


def test_repl_help_specific_command_shows_options(monkeypatch, capsys):
    out = _run_repl_with(["help generate", "exit"], monkeypatch, capsys)
    assert "Usage: docgen generate" in out
    assert "--template" in out


def test_repl_help_subcommand_shows_options(monkeypatch, capsys):
    out = _run_repl_with(["help config set", "exit"], monkeypatch, capsys)
    assert "Usage: docgen config set" in out
    assert "key" in out


def test_repl_help_unknown_command(monkeypatch, capsys):
    out = _run_repl_with(["help nope", "exit"], monkeypatch, capsys)
    assert "Unknown command" in out
    assert "nope" in out


def test_repl_version_prints_version(monkeypatch, capsys):
    from docgen import __version__

    out = _run_repl_with(["version", "exit"], monkeypatch, capsys)
    assert __version__ in out


def _fake_questionary(monkeypatch):
    class FakePrompt:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    monkeypatch.setattr(questionary, "select", lambda *a, **k: FakePrompt("deepseek"))
    monkeypatch.setattr(
        questionary, "text", lambda *a, **k: FakePrompt("https://api.deepseek.com")
    )
    monkeypatch.setattr(questionary, "password", lambda *a, **k: FakePrompt("sk-test"))
    monkeypatch.setattr(questionary, "confirm", lambda *a, **k: FakePrompt(True))

    import docgen.config as config_mod

    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: {})
    monkeypatch.setattr(config_mod, "save_config", lambda *a, **k: None)


def test_run_onboarding_uses_bare_form_when_interactive(monkeypatch, capsys):
    _fake_questionary(monkeypatch)

    run_onboarding(interactive=True)
    out = capsys.readouterr().out
    assert "config set" in out
    assert "docgen config set" not in out


def test_run_onboarding_uses_docgen_form_by_default(monkeypatch, capsys):
    _fake_questionary(monkeypatch)

    run_onboarding()
    out = capsys.readouterr().out
    assert "docgen config set" in out
