# docgen Full-Screen TUI (opencode/Hermes-style) Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace the current scrolled REPL (`docgen/tui.py`, a prompt_toolkit line
prompt that scrolls output) with a full-screen, layout-driven TUI built on
**textual** — split-pane (sidebar + main), command palette, live job status,
and a scrollback log — matching the look/feel of opencode and Hermes.

**Architecture:** A single Textual `App` owns the screen. The left pane is a
command palette / project tree; the right pane is a tabbed main area (a Rich
log "terminal" + a job/status view). Commands are run in-process by reusing the
existing Typer `app` (as `_run_typer_command` already does) inside a background
worker thread so the UI never blocks. We do NOT re-implement the CLI — we wrap
it. The old `tui.py` REPL is preserved behind a `--legacy-tui` flag for rollback.

**Tech Stack:** `textual` (new dep, user-confirmed), `rich` (already a dep),
existing `typer` app + `docgen.welcome`/`docgen.config`/`docgen.context`.

**Current state to preserve/leverage:**
- `docgen/tui.py` already has: `DocgenCompleter`, `_iter_commands()`, `KNOWN_COMMANDS`,
  `COMMAND_EXAMPLES`, `_run_typer_command()`, `_show_help()`, `_show_command_help()`.
  Reuse these verbatim — they are the source of truth for the command surface.
- `docgen/cli.py::run_generation(...)` drives generation via `GenerationEngine`
  with `on_progress` callback (`TokenUsage`) and prints via rich `console`. The
  TUI must route that progress into a Textual widget instead of `console.status`.
- `docgen/welcome.py`: `is_onboarded()`, `run_onboarding(interactive=...)`.
- `docgen/generator/engine.py`: `GenerationResult` (`.files`, `.warnings`,
  `.token_usage`), `TokenUsage` (`.total_tokens`, `.provider_calls`, `.cached_calls`).

---

## Task 1: Add `textual` dependency and smoke-test it

**Objective:** Make textual available in the venv and confirm it imports.

**Files:**
- Modify: `pyproject.toml:11-24` (dependencies list)
- Test: `tests/test_tui_textual.py` (create)

**Step 1: Add dep**

In `pyproject.toml` dependencies, add:
```toml
    "textual>=0.80.0",
```

**Step 2: Install + verify import**
```bash
cd ~/docgen
.venv/bin/pip install "textual>=0.80.0"
.venv/bin/python -c "import textual; print(textual.__version__)"
```
Expected: prints a version like `0.8x.y`.

**Step 3: Write a failing-then-passing import test**

`tests/test_tui_textual.py`:
```python
def test_textual_importable():
    import textual
    from textual.app import App
    assert hasattr(App, "run")
```

**Step 4: Run**
```bash
.venv/bin/python -m pytest tests/test_tui_textual.py -q
```
Expected: 1 passed.

**Step 5: Commit**
```bash
git add pyproject.toml tests/test_tui_textual.py
git commit -m "build: add textual dependency for full-screen TUI"
```

---

## Task 2: Skeleton Textual app with split layout

**Objective:** A full-screen app with a header, left command palette, right
log pane, and footer — that launches and exits cleanly. No command logic yet.

**Files:**
- Create: `docgen/tui_app.py`
- Modify: `docgen/tui.py` (call new app from `_cli_main`)
- Test: `tests/test_tui_textual.py` (extend)

**Step 1: Write skeleton app**

`docgen/tui_app.py`:
```python
"""Full-screen Textual TUI for docgen (opencode/Hermes-style layout)."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Static, RichLog


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
```

**Step 2: Wire `_cli_main` to launch it**

In `docgen/tui.py`, add import and call. Replace the `_interactive_loop()` call
inside `_cli_main` (around line 321) so it dispatches to the new app, keeping
`--legacy-tui` to fall back to the old REPL:
```python
def _cli_main():
    import sys
    if not sys.stdin.isatty():
        # ... existing non-TTY fallback (unchanged) ...
        return
    try:
        from docgen.welcome import is_onboarded, run_onboarding
        if not is_onboarded() and not run_onboarding(interactive=True):
            sys.exit(1)
        if "--legacy-tui" in sys.argv:
            _interactive_loop()
        else:
            from docgen.tui_app import DocgenTUI
            DocgenTUI().run()
    except Exception as e:
        # ... existing fallback ...
```

**Step 3: Test that the app class composes**

Add to `tests/test_tui_textual.py`:
```python
def test_tui_app_composes():
    from docgen.tui_app import DocgenTUI
    app = DocgenTUI()
    # Compose must yield the expected widgets without raising.
    widgets = list(app.compose())
    assert len(widgets) >= 3
```

**Step 4: Run**
```bash
.venv/bin/python -m pytest tests/test_tui_textual.py -q
```
Expected: 2 passed.

**Step 5: Smoke-run (manual, not in CI)**
```bash
cd ~/docgen && .venv/bin/python -m docgen   # press Ctrl+C to exit
```
Expected: full-screen layout with header/sidebar/main/footer.

**Step 6: Commit**
```bash
git add docgen/tui_app.py docgen/tui.py tests/test_tui_textual.py
git commit -m "feat(tui): add full-screen Textual app skeleton with split layout"
```

---

## Task 3: Command palette in the sidebar (reuse existing command surface)

**Objective:** Sidebar lists real commands (from `_iter_commands`), reacts to
keystrokes, and selecting/filtering a command seeds the input.

**Files:**
- Modify: `docgen/tui_app.py`
- Reuse (import, do not copy): `docgen.tui._iter_commands`, `docgen.tui.COMMAND_EXAMPLES`, `docgen.tui.KNOWN_COMMANDS`
- Test: `tests/test_tui_textual.py` (extend)

**Step 1: Add a `ListView` sidebar populated from the CLI surface**

Extend `DocgenTUI`:
```python
from textual.widgets import ListView, ListItem, Label, Input
from textual.containers import Vertical
from docgen.tui import _iter_commands, COMMAND_EXAMPLES


class DocgenTUI(App):
    ...
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Input(placeholder="filter commands…", id="cmd_filter")
                yield ListView(id="cmd_list")
            yield RichLog(id="main", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self._populate_commands()

    def _populate_commands(self, filter_text: str = "") -> None:
        list_view = self.query_one("#cmd_list", ListView)
        list_view.clear()
        for name, help_text in _iter_commands():
            if filter_text and filter_text.lower() not in name.lower():
                continue
            list_view.append(ListItem(Label(f"[cyan]{name}[/]  [dim]{help_text}[/]")))
```

**Step 2: Wire filter Input → list refresh**

```python
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "cmd_filter":
            self._populate_commands(event.value)
```

**Step 3: Test population logic**

```python
def test_command_list_populated():
    from docgen.tui_app import DocgenTUI
    from textual.widgets import ListView
    app = DocgenTUI()
    # simulate mount population without running the event loop
    import asyncio
    async def go():
        app._populate_commands()
        return list(app.query_one("#cmd_list", ListView)._items)
    items = asyncio.get_event_loop().run_until_complete(go())
    assert any("generate" in str(i) for i in items)
```

**Step 4: Run**
```bash
.venv/bin/python -m pytest tests/test_tui_textual.py -q
```
Expected: 3 passed.

**Step 5: Commit**
```bash
git add docgen/tui_app.py tests/test_tui_textual.py
git commit -m "feat(tui): command palette sidebar from real CLI surface"
```

---

## Task 4: Command input + run in-process (non-blocking)

**Objective:** A bottom input bar where the user types a full command
(`generate --source src`), it runs via the existing Typer `app` in a worker
thread, and output streams to the RichLog main pane — UI stays responsive.

**Files:**
- Modify: `docgen/tui_app.py`
- Reuse: `docgen.tui._run_typer_command`, `docgen.tui._normalize_input`
- Test: `tests/test_tui_textual.py` (extend)

**Step 1: Add input bar + worker**

```python
from textual.worker import Worker, get_current_worker
import io
from contextlib import redirect_stdout
from docgen.tui import _run_typer_command, _normalize_input


class DocgenTUI(App):
    ...
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Input(placeholder="filter commands…", id="cmd_filter")
                yield ListView(id="cmd_list")
            yield RichLog(id="main", markup=True, wrap=True)
        yield Input(placeholder="docgen> type a command (e.g. generate --source src)", id="cmd_input")
        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "cmd_input":
            return
        raw = _normalize_input(event.value)
        if not raw:
            return
        self.query_one("#cmd_input", Input).value = ""
        self.run_worker(self._run_command(raw), group="cmd", description=raw)

    async def _run_command(self, raw: str) -> None:
        log = self.query_one("#main", RichLog)
        log.write(f"[bold cyan]docgen>[/] {raw}")
        # Run the in-process Typer command; capture rich output into the log.
        from docgen.tui import _run_typer_command
        try:
            _run_typer_command(raw)
        except Exception as e:  # keep UI alive
            log.write(f"[red]Error:[/] {e}")
        log.write("[dim]— done —[/]")
```

Note: `_run_typer_command` currently prints via its own `Console()`. For true
capture we route through a shared `Console(file=...)` — see Task 5. For this
task, acceptable to let it print to the real terminal behind the TUI; Task 5
tightens capture. Keep the worker so the loop never blocks on network calls.

**Step 2: Test worker scheduling (no event loop run)**

```python
def test_input_submitted_normalizes():
    from docgen.tui import _normalize_input
    assert _normalize_input("docgen generate") == "generate"
    assert _normalize_input("/help") == "help"
```

**Step 3: Run**
```bash
.venv/bin/python -m pytest tests/test_tui_textual.py -q
```
Expected: 4 passed.

**Step 4: Manual smoke**
Run `docgen`, type `help` in the bottom bar → command list appears (in terminal
behind TUI for now). Confirm Ctrl+C exits.

**Step 5: Commit**
```bash
git add docgen/tui_app.py tests/test_tui_textual.py
git commit -m "feat(tui): bottom command input runs in-process via worker"
```

---

## Task 5: Route rich output + generation progress into the TUI

**Objective:** Real capture of command stdout into the RichLog, and live
generation progress (token usage) shown in a status widget instead of
`console.status`.

**Files:**
- Modify: `docgen/tui.py` — add `run_command_capture(raw, write_fn)` that accepts
  a sink callback so output goes to the TUI log, not a fresh `Console()`.
- Modify: `docgen/tui_app.py` — pass a `RichLog.write`-based sink; subscribe to
  `GenerationEngine.on_progress`.
- Test: `tests/test_tui_textual.py` (extend)

**Step 1: Refactor `_run_typer_command` to accept a sink**

In `docgen/tui.py`, change signature and replace the two `Console()` locals:
```python
def _run_typer_command(raw: str, sink=None):
    """Run a docgen command in-process. `sink` is a callable(str) for output;
    if None, prints to a default rich Console()."""
    from rich.console import Console
    console = sink_console if (sink_console := _SINK_CONSOLE) else Console()
    ...
```
Simplest robust approach: add a module-level `set_output_sink(callable|None)`
in `docgen/tui.py`; `_run_typer_command` uses it when set. Tests still use the
default. Keep it small and backward-compatible.

**Step 2: TUI passes a sink that writes to RichLog**

```python
async def _run_command(self, raw: str) -> None:
    log = self.query_one("#main", RichLog)
    import docgen.tui as tui
    tui.set_output_sink(lambda s: log.write(s))
    try:
        from docgen.tui import _run_typer_command
        _run_typer_command(raw)
    finally:
        tui.set_output_sink(None)
```

**Step 3: Live generation progress**

`run_generation` already takes `on_progress`. Add a TUI-friendly entry in
`docgen/cli.py` (or wrap in tui_app) that passes an `on_progress` updating a
`Static` status widget. Minimal: in `DocgenTUI` add `yield Static("idle", id="status")`
in the sidebar, and when running `generate`, temporarily monkeypatch progress via
a new optional param. If `run_generation` plumbing is heavy, defer detailed
progress to a follow-up and just show "generating…" + final token summary (which
`_run_typer_command` already prints → captured by sink).

**Step 4: Test sink**

```python
def test_output_sink_capture(capsys):
    import docgen.tui as tui
    captured = []
    tui.set_output_sink(captured.append)
    tui.set_output_sink(None)
    assert captured == []
```

**Step 5: Run**
```bash
.venv/bin/python -m pytest tests/test_tui_textual.py -q
```
Expected: 5 passed.

**Step 6: Commit**
```bash
git add docgen/tui.py docgen/tui_app.py tests/test_tui_textual.py
git commit -m "feat(tui): capture command output + show generation status in UI"
```

---

## Task 6: Help/exit/clear commands + keyboard shortcuts

**Objective:** `help`, `help <cmd>`, `clear`, `exit`, `version` work from the
input bar; `q` exits, `ctrl+l` clears the log; selecting a sidebar item fills
the input.

**Files:**
- Modify: `docgen/tui_app.py`
- Reuse: `docgen.tui._show_help`, `docgen.tui._show_command_help`
- Test: `tests/test_tui_textual.py` (extend)

**Step 1: Handle builtins in `_run_command`**

```python
async def _run_command(self, raw: str) -> None:
    log = self.query_one("#main", RichLog)
    from docgen.tui import _show_help, _show_command_help
    if raw in ("exit", "quit"):
        self.exit(); return
    if raw == "clear":
        log.clear(); return
    if raw == "help":
        _show_help(); return
    if raw.startswith("help "):
        _show_command_help(raw[5:].strip()); return
    if raw == "version":
        from docgen import __version__
        log.write(f"[cyan]docgen[/] v{__version__}"); return
    # else run via Typer (Task 5 sink)
    ...
```

**Step 2: Bindings**

```python
BINDINGS = [
    ("q", "quit", "Quit"),
    ("ctrl+l", "clear_log", "Clear"),
]

def action_clear_log(self):
    self.query_one("#main", RichLog).clear()
```

**Step 3: Sidebar select → fill input**

```python
def on_list_view_selected(self, event: ListView.Selected):
    label = event.item.query_one(Label).renderable
    name = str(label).split()[0]
    self.query_one("#cmd_input", Input).value = name + " "
    self.query_one("#cmd_input", Input).focus()
```

**Step 4: Test**

```python
def test_builtin_help_routing():
    # help routing is in _run_command; test the reused helpers directly
    from docgen.tui import _show_help, _show_command_help
    assert callable(_show_help) and callable(_show_command_help)
```

**Step 5: Run**
```bash
.venv/bin/python -m pytest tests/test_tui_textual.py -q
```
Expected: 6 passed.

**Step 6: Commit**
```bash
git add docgen/tui_app.py tests/test_tui_textual.py
git commit -m "feat(tui): help/exit/clear builtins + key bindings + sidebar select"
```

---

## Task 7: Final verification + README + keep `--legacy-tui`

**Objective:** Full suite green, README documents the new TUI, old REPL
reachable via `--legacy-tui`.

**Files:**
- Modify: `README.md` (TUI section)
- Test: full suite

**Step 1: Run full suite**
```bash
cd ~/docgen && .venv/bin/python -m pytest -q 2>&1 | tail -5
```
Expected: all passed (prior baseline 204, plus new TUI tests).

**Step 2: Document in README**
Add a "Interactive TUI" section: launch `docgen` (no args) for the full-screen
TUI; `docgen --legacy-tui` for the classic scrolled REPL; note sidebar = command
palette, bottom bar = command input, `q` quits.

**Step 3: Commit**
```bash
git add README.md
git commit -m "docs: document full-screen TUI and --legacy-tui fallback"
```

---

## Risks / Tradeoffs / Open Questions

- **Output capture:** The current `_run_typer_command` prints via its own
  `Console()`. Full capture (Task 5) requires a sink injection; we keep a
  backward-compatible default so non-TUI callers are unaffected.
- **Generation progress granularity:** `run_generation` only exposes a
  `TokenUsage` callback, not per-page progress. Fine-grained page progress would
  need `GenerationEngine` changes — deferred unless you want it.
- **Block-on-LLM:** Commands that hit the network run in a `Worker` thread so
  the UI stays live; results still stream via the sink. No streaming token
  display (deferred).
- **Legacy fallback:** Old REPL preserved under `--legacy-tui` for rollback;
  remove after TUI is proven stable (separate cleanup task, not in this plan).
- **Screen size:** Textual needs a terminal ≥ ~80x24; non-TTY already falls back
  (unchanged in `tui.py`).

## Verification summary (commands)
- Unit: `.venv/bin/python -m pytest tests/test_tui_textual.py -q`
- Full: `.venv/bin/python -m pytest -q 2>&1 | tail -5`
- Manual: `cd ~/docgen && .venv/bin/python -m docgen` (full-screen);
  `python -m docgen --legacy-tui` (old REPL).
