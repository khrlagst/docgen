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
