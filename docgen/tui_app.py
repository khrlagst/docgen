"""Full-screen Textual TUI for docgen (opencode/Hermes-style layout).

Split-pane: a header, a left sidebar (command palette) and a right main
RichLog "terminal", plus a footer. Commands are run in-process by reusing the
existing Typer ``app`` so we never re-implement the CLI surface.
"""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header, RichLog, Static


class DocgenTUI(App):
    TITLE = "docgen"
    SUB_TITLE = "documentation generator"

    CSS = """
    #sidebar { width: 30%; border-right: solid $accent; }
    #main { width: 1fr; }
    RichLog { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield Static("Commands\n(placeholder)", id="sidebar")
            yield RichLog(id="main", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "docgen"
