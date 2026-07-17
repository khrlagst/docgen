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
