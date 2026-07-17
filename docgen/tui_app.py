"""Full-screen Textual TUI for docgen (opencode/Hermes-style layout).

Split-pane: a header, a left sidebar (command palette) and a right main
RichLog "terminal", plus a footer. Commands are run in-process by reusing the
existing Typer ``app`` so we never re-implement the CLI surface.
"""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, ListView, ListItem, Label, RichLog, Static

from docgen.tui import _iter_commands


class DocgenTUI(App):
    TITLE = "docgen"
    SUB_TITLE = "documentation generator"

    CSS = """
    #sidebar { width: 30%; border-right: solid $accent; }
    #cmd_filter { dock: top; }
    #cmd_list { height: 1fr; }
    #main { width: 1fr; }
    RichLog { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Input(placeholder="filter commands…", id="cmd_filter")
                yield ListView(id="cmd_list")
            yield RichLog(id="main", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "docgen"
        self.run_worker(self._populate_commands(), group="ui")

    async def _populate_commands(self, filter_text: str = "") -> None:
        from textual.widgets import ListView

        list_view = self.query_one("#cmd_list", ListView)
        # `ListView.clear()` is awaitable in Textual 8.x (schedules removal);
        # awaiting it actually empties the list before we re-add rows.
        await list_view.clear()
        for name, help_text in _iter_commands():
            if filter_text and filter_text.lower() not in name.lower():
                continue
            list_view.append(
                ListItem(Label(f"[cyan]{name}[/]  [dim]{help_text}[/]"))
            )

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "cmd_filter":
            await self._populate_commands(event.value)
