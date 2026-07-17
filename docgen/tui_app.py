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

from docgen.tui import (
    _iter_commands,
    _normalize_input,
    _run_typer_command,
    _show_command_help,
    _show_help,
)
from docgen import __version__


class DocgenTUI(App):
    TITLE = "docgen"
    SUB_TITLE = "documentation generator"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+l", "clear_log", "Clear"),
    ]

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

    def action_quit(self) -> None:
        self.exit()

    def action_clear_log(self) -> None:
        self.query_one("#main", RichLog).clear()

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
            item = ListItem(Label(f"[cyan]{name}[/]  [dim]{help_text}[/]"))
            # Stash the bare command name so selection can prefill the input
            # without scraping rich renderables (Label has no .renderable).
            item.command_name = name
            list_view.append(item)

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

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        # Fill the input with the chosen command name for quick editing.
        name = getattr(event.item, "command_name", None)
        if not name:
            label = event.item.query_one(Label)
            name = str(label.renderable).split()[0]
        inp = self.query_one("#cmd_input", Input)
        inp.value = name + " "
        inp.focus()

    async def _run_command(self, raw: str) -> None:
        from textual.widgets import RichLog

        import docgen.tui as _tui

        raw = _normalize_input(raw)
        if not raw:
            return
        log = self.query_one("#main", RichLog)
        log.write(f"[bold cyan]docgen>[/] {raw}")

        # Redirect all command stdout (incl. rich Console output) into the log,
        # covering both Typer commands and the REPL builtins (help, etc.).
        def _sink(text: str) -> None:
            text = text.rstrip("\n")
            if text:
                log.write(text)

        _tui.set_output_sink(_sink)
        try:
            # Builtins handled directly (no Typer dispatch).
            if raw in ("exit", "quit"):
                self.exit()
                return
            if raw == "clear":
                log.clear()
                return
            if raw == "version":
                log.write(f"[cyan]docgen[/] v{__version__}")
                return
            if raw == "help":
                _show_help()
                return
            if raw.startswith("help "):
                _show_command_help(raw[5:].strip())
                return

            _tui._run_typer_command(raw)
        except Exception as e:  # keep the UI alive on unexpected errors
            log.write(f"[red]Error:[/] {e}")
        finally:
            _tui.set_output_sink(None)
        log.write("[dim]— done —[/]")

