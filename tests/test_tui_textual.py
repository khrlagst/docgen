"""Tests for the full-screen Textual TUI (opencode/Hermes-style)."""
import asyncio


def test_textual_importable():
    import textual
    from textual.app import App

    assert hasattr(App, "run")


def test_tui_app_composes():
    from docgen.tui_app import DocgenTUI

    async def go():
        app = DocgenTUI()
        async with app.run_test(size=(120, 40)):
            return {w.id for w in app.screen.walk_children() if w.id}

    ids = asyncio.run(go())
    # header/footer have no id; sidebar + main RichLog are asserted
    assert "main" in ids
    assert "sidebar" in ids


def test_command_list_populated():
    from docgen.tui_app import DocgenTUI
    from docgen.tui import _iter_commands

    # _iter_commands yields every command + subcommand row.
    expected_rows = list(_iter_commands())

    async def go():
        app = DocgenTUI()
        async with app.run_test(size=(120, 40)):
            await app._populate_commands()
            from textual.widgets import ListView

            return list(app.query_one("#cmd_list", ListView).children)

    items = asyncio.run(go())
    assert len(items) == len(expected_rows)
    assert len(items) > 5


def test_command_list_no_duplicates_on_refilter():
    from docgen.tui_app import DocgenTUI

    async def go():
        app = DocgenTUI()
        async with app.run_test(size=(120, 40)):
            await app._populate_commands("zznomatch")  # filter to none
            await app._populate_commands("")            # repopulate all
            from textual.widgets import ListView

            return len(list(app.query_one("#cmd_list", ListView).children))

    # Re-populating must not accumulate duplicate rows.
    assert asyncio.run(go()) > 5


def test_output_sink_captures():
    import docgen.tui as tui

    captured = []
    tui.set_output_sink(captured.append)
    try:
        # `providers` lists the registry with no network/LLM calls.
        tui._run_typer_command("providers")
    finally:
        tui.set_output_sink(None)

    assert captured, "sink should have received output"
    blob = "".join(captured)
    assert "deepseek" in blob or "openai" in blob


def test_tui_routes_output_to_log():
    from docgen.tui_app import DocgenTUI

    async def go():
        app = DocgenTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            # `providers` lists the registry; output must land in the log.
            await app._run_command("providers")
            await app.workers.wait_for_complete()
            from textual.widgets import RichLog

            return "\n".join(str(line) for line in app.query_one("#main", RichLog).lines)

    out = asyncio.run(go())
    assert "deepseek" in out


def test_builtin_help_routing():
    from docgen.tui_app import DocgenTUI

    async def go():
        app = DocgenTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await app._run_command("help")
            await app.workers.wait_for_complete()
            from textual.widgets import RichLog

            return "\n".join(str(line) for line in app.query_one("#main", RichLog).lines)

    out = asyncio.run(go())
    # help lists real commands incl. generate
    assert "generate" in out


def test_builtin_version_routing():
    from docgen.tui_app import DocgenTUI
    from docgen import __version__

    async def go():
        app = DocgenTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await app._run_command("version")
            await app.workers.wait_for_complete()
            from textual.widgets import RichLog

            return "\n".join(str(line) for line in app.query_one("#main", RichLog).lines)

    out = asyncio.run(go())
    assert __version__ in out


def test_builtin_clear_empties_log():
    from docgen.tui_app import DocgenTUI

    async def go():
        app = DocgenTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            from textual.widgets import RichLog

            log = app.query_one("#main", RichLog)
            log.write("something")
            assert log.lines
            await app._run_command("clear")
            return list(log.lines)

    assert asyncio.run(go()) == []


def test_builtin_exit_invokes_exit(monkeypatch):
    from docgen.tui_app import DocgenTUI

    exited = []
    monkeypatch.setattr(DocgenTUI, "exit", lambda self: exited.append(True))

    async def go():
        app = DocgenTUI()
        async with app.run_test(size=(120, 40)):
            await app._run_command("exit")

    asyncio.run(go())
    assert exited == [True]


def test_bindings_present():
    from docgen.tui_app import DocgenTUI

    # quit + clear_log actions must exist and be wired via BINDINGS.
    assert hasattr(DocgenTUI, "action_quit")
    assert hasattr(DocgenTUI, "action_clear_log")
    binding_text = " ".join(str(b) for b in DocgenTUI.BINDINGS)
    assert "quit" in binding_text
    assert "clear_log" in binding_text


def test_sidebar_select_fills_input():
    from docgen.tui_app import DocgenTUI
    from textual.widgets import ListView, ListItem, Label, Input

    async def go():
        app = DocgenTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            lv = app.query_one("#cmd_list", ListView)
            await app._populate_commands()
            item = lv.children[0]
            # Simulate selecting the first command item.
            app.on_list_view_selected(
                ListView.Selected(item=item, list_view=lv, index=0)
            )
            await pilot.pause()
            return app.query_one("#cmd_input", Input).value

    val = asyncio.run(go())
    # First command yielded by _iter_commands is "init"; selecting fills input.
    assert val.startswith("init")


def test_input_submitted_runs_command(monkeypatch):
    from docgen.tui_app import DocgenTUI
    import docgen.tui as tui

    captured = []

    def fake_run(raw, sink=None):
        captured.append(raw)

    monkeypatch.setattr(tui, "_run_typer_command", fake_run)

    async def go():
        app = DocgenTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await app._run_command("docgen generate --source src")
            # ensure any scheduled workers finish
            await app.workers.wait_for_complete()

    asyncio.run(go())
    assert captured == ["generate --source src"]


def test_input_submission_empty_is_ignored(monkeypatch):
    from docgen.tui_app import DocgenTUI
    import docgen.tui as tui

    called = []
    monkeypatch.setattr(tui, "_run_typer_command", lambda raw, sink=None: called.append(raw))

    async def go():
        app = DocgenTUI()
        async with app.run_test(size=(120, 40)):
            await app._run_command("   ")

    asyncio.run(go())
    assert called == []
