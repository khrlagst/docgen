"""Tests for the full-screen Textual TUI (opencode/Hermes-style)."""


def test_textual_importable():
    import textual
    from textual.app import App

    assert hasattr(App, "run")
