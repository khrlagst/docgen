"""Full-screen Textual TUI for docgen (opencode/Hermes-style layout).

Split-pane: a header, a left sidebar (command palette) and a right main
RichLog "terminal", plus a footer. Commands are run in-process by reusing the
existing Typer ``app`` so we never re-implement the CLI surface.
"""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
)

from docgen.tui import _iter_commands, _normalize_input

class DocgenTUI(App):
    TITLE = "docgen"
    SUB_TITLE = "documentation generator"

    CSS = """
    #sidebar { width: 30%; border-right: solid $accent; }
    #cmd_filter { dock: top; }
    #cmd_list { height: 1fr; }
    #main { width: 1fr; }
    RichLog { height: 1fr; }
    #cmd_input { dock: bottom; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Input(placeholder="filter commands…", id="cmd_filter")
                yield ListView(id="cmd_list")
            yield RichLog(id="main", markup=True, wrap=True)
        yield Input(
            placeholder="docgen> type a command (e.g. generate --source src)",
            id="cmd_input",
        )
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "cmd_input":
            return
        self.query_one("#cmd_input", Input).value = ""
        # Normalization + dispatch happens in _run_command; run in a worker so
        # network/LLM calls never block the UI thread.
        self.run_worker(self._run_command(event.value), group="cmd")

    async def _run_command(self, raw: str) -> None:
        from textual.widgets import RichLog

        raw = _normalize_input(raw)
        if not raw:
            return
        log = self.query_one("#main", RichLog)
        log.write(f"[bold cyan]docgen>[/] {raw}")
        try:
            # Look up through the module so tests can monkeypatch
            # `docgen.tui._run_typer_command` without touching this import.
            import docgen.tui as _tui

            _tui._run_typer_command(raw)
        except Exception as e:  # keep the UI alive on unexpected errors
            log.write(f"[red]Error:[/] {e}")
        log.write("[dim]— done —[/]")
