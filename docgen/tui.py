"""Interactive terminal UI for docgen."""

import shlex
import sys
from pathlib import Path
from typing import Any, Iterable

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import typer
from typer._click.exceptions import UsageError, Abort, NoArgsIsHelpError
from typer.main import get_command

from docgen import __version__
from docgen.cli import app
from docgen.welcome import LOGO
from docgen.config import CONFIG_KEY_REFERENCE
from docgen.llm.factory import PROVIDER_REGISTRY

KNOWN_COMMANDS = set(get_command(app).commands.keys())

# Curated one-line examples for the most-used commands. The *set* of commands
# and their descriptions is derived from the real Typer app (see `_iter_commands`)
# so the help listing can never drift out of sync with the actual CLI surface.
COMMAND_EXAMPLES: dict[str, str] = {
    "init": "init . --force",
    "generate": "generate --source src --template wiki",
    "refine": "refine docs/index.md --prompt 'Add more examples'",
    "serve": "serve --port 8080 --watch",
    "export": "export docs docs.pdf",
    "html": "html docs docs.html",
    "site": "site docs mkdocs-site",
    "providers": "providers",
    "models": "models --provider openai",
    "setup": "setup",
    "legal": "legal",
    "config": "config set llm.model deepseek-chat",
    "config show": "config show",
    "config set": "config set llm.model deepseek-chat",
    "config validate": "config validate",
    "cache clear": "cache clear",
}


def _iter_commands():
    """Yield (name, help_text) for every command, including subcommands.

    Single source of truth = the real Typer ``app``. Used by the help table,
    the completer, and the toolbar so newly added commands (e.g. ``providers``,
    ``models``, ``cache``) appear automatically without manual bookkeeping.
    """
    root = get_command(app)
    for name, cmd in root.commands.items():
        help_text = (cmd.help or "").strip().split("\n")[0]
        yield name, help_text
        subcommands = getattr(cmd, "commands", None)
        if subcommands:
            for sub_name, sub in subcommands.items():
                sub_help = (sub.help or "").strip().split("\n")[0]
                yield f"{name} {sub_name}", sub_help

BANNER = LOGO

STYLE = Style.from_dict(
    {
        "prompt": "ansicyan bold",
        "toolbar": "ansiwhite bold",
        "completion-menu": "bg:ansiblack ansigreen",
        "completion-menu.completion": "bg:ansibrightblack ansiwhite",
        "completion-menu.completion.current": "bg:ansicyan ansiwhite",
    }
)


def _run_typer_command(raw: str):
    """Run a docgen command in-process (no subprocess, so no `python -m docgen`
    leakage in errors) with real terminal I/O."""
    parts = shlex.split(raw, posix=False)
    try:
        app(parts, standalone_mode=False, prog_name="docgen")
    except typer.Exit:
        pass
    except NoArgsIsHelpError:
        # `no_args_is_help` already printed the help; clean exit, no error line.
        pass
    except Abort:
        pass
    except UsageError as e:
        console = Console()
        if e.message:
            console.print(f"[red]{e.message}[/]")
        console.print("[dim]Type 'help' to see available commands.[/]")
    except SystemExit:
        # `command --help` ends via ctx.exit(0); keep the REPL alive.
        pass
    except Exception as e:  # keep the REPL alive on unexpected errors
        console = Console()
        console.print(f"[red]Error:[/] {e}")


def _normalize_input(text: str) -> str:
    """Normalize REPL input so both `config` and `docgen config` work.

    Strips an optional leading `/` (completion hint style) and an optional
    leading `docgen ` prefix, since inside the REPL you type the bare command.
    """
    text = text.strip().lstrip("/").strip()
    if text.lower().startswith("docgen "):
        text = text[7:].strip()
    return text


def _show_help():
    """Show command help table, derived from the real CLI surface."""
    console = Console()
    table = Table(box=None, show_header=False)
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description")
    table.add_column("Example", style="dim")

    for name, help_text in _iter_commands():
        table.add_row(name, help_text or "", COMMAND_EXAMPLES.get(name, ""))

    console.print(table)
    console.print("\n[dim]Tip: Type any command with its arguments just like in the terminal.[/]")
    console.print(
        "[dim]Type 'help <command>' (e.g. 'help generate' or 'help config set') "
        "for that command's options and subcommands.[/]"
    )


def _show_command_help(command: str):
    """Show the detailed typer help for a single command (options + subcommands).

    Routes through the in-process runner so ``<command> --help`` prints without
    leaking a ``python -m docgen`` subprocess, and the resulting SystemExit is
    swallowed to keep the REPL alive.
    """
    console = Console()
    if not command or command.strip() == "help":
        _show_help()
        return

    parts = shlex.split(command, posix=False)
    if parts[0] not in KNOWN_COMMANDS:
        console.print(f"[red]Unknown command:[/] {parts[0]}")
        console.print("[dim]Type 'help' to see available commands.[/]")
        return

    _run_typer_command(f"{command} --help")


def _show_banner():
    from docgen.welcome import is_first_run

    console = Console()
    console.print()
    console.print(BANNER)

    if is_first_run():
        console.print(
            "[dim]This is your first time running DOCGEN![/]\n"
            "[dim]Type [bold]help[/] to see available commands, or just type one directly.[/]"
        )
    else:
        console.print(
            "[dim]Type [bold]help[/] for commands, [bold]exit[/] to quit.[/]"
        )


class DocgenCompleter(Completer):
    """Context-aware completer for the REPL.

    Completes command/subcommand names (derived from the real CLI surface),
    plus the *values* of ``config set``: the key is completed from
    ``CONFIG_KEY_REFERENCE``, and the value is completed from the key's choice
    list (provider/template/engine) or the provider catalog.
    """

    def __init__(self):
        self._command_words = [name for name, _ in _iter_commands()] + [
            "help",
            "exit",
            "clear",
            "version",
        ]

    def _complete_config_set(self, words: list[str], word_before: str) -> Iterable[Completion]:
        # words excludes the current (incomplete) token; word_before is it.
        # `config set` -> complete keys
        if len(words) == 2:  # ['config', 'set']
            for key in CONFIG_KEY_REFERENCE:
                if key.startswith(word_before):
                    yield Completion(key, start_position=-len(word_before))
            return
        # `config set llm.provider` -> complete value for that key
        if len(words) == 3 and words[2].startswith("llm."):
            ref = CONFIG_KEY_REFERENCE.get(words[2])
            pool = ref.get("choices") if ref else None
            if words[2] == "llm.provider":
                pool = sorted(PROVIDER_REGISTRY.keys())
            for val in pool or []:
                if val.startswith(word_before):
                    yield Completion(val, start_position=-len(word_before))

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        # Strip a leading 'docgen ' since inside the REPL you type bare commands.
        if text.lower().startswith("docgen "):
            text = text[7:].strip()

        words = shlex.split(text, posix=False) if text else []
        word_before = words[-1] if words and not text.endswith(" ") else ""
        # If the cursor is right after a space, words won't include an empty
        # token; we still want to complete the *next* token.
        if text.endswith(" "):
            word_before = ""

        if words and words[0] == "config" and len(words) >= 2 and words[1] == "set":
            yield from self._complete_config_set(words, word_before)
            return

        for word in self._command_words:
            if word.startswith(word_before):
                yield Completion(word, start_position=-len(word_before))


def _interactive_loop():
    """Run the interactive prompt loop (requires a real terminal)."""
    import prompt_toolkit

    history_file = str(Path.home() / ".config" / "docgen" / "history")
    Path(history_file).parent.mkdir(parents=True, exist_ok=True)

    completer = DocgenCompleter()

    session: PromptSession = PromptSession(
        history=FileHistory(history_file),
        completer=completer,
        style=STYLE,
        complete_while_typing=True,
    )

    _show_banner()

    while True:
        try:
            text = session.prompt(
                HTML("<ansicyan>docgen&gt;</ansicyan> "),
                bottom_toolbar=HTML(
                    "<ansibrightblack>"
                    + "  ".join(sorted(get_command(app).commands.keys()) + ["help", "exit"])
                    + "</ansibrightblack>"
                ),
            )
        except (KeyboardInterrupt, EOFError):
            console = Console()
            console.print("\n[yellow]Goodbye![/]")
            break

        text = _normalize_input(text)
        if not text:
            continue

        if text == "exit":
            console = Console()
            console.print("[yellow]See you again soon![/]")
            break

        if text == "clear":
            Console().clear()
            _show_banner()
            continue

        if text == "help":
            _show_help()
            continue

        if text.startswith("help "):
            _show_command_help(text[5:].strip())
            continue

        if text == "version":
            Console().print(f"[cyan]docgen[/] v{__version__}")
            continue

        parts = shlex.split(text, posix=False)
        if parts and parts[0] not in KNOWN_COMMANDS:
            console = Console()
            console.print(f"[red]Unknown command:[/] {parts[0]}")
            console.print("[dim]Type 'help' to see available commands.[/]")
            continue

        _run_typer_command(text)


def _cli_main():
    """Launch the interactive TUI, with fallback for non-TTY."""
    import sys

    if not sys.stdin.isatty():
        console = Console()
        console.print("[yellow]docgen[/] — run with no arguments for interactive mode, or use [green]docgen <command>[/]")
        available = ", ".join(sorted(get_command(app).commands.keys()))
        console.print(f"[dim]Available commands: {available}[/]")
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
        console = Console()
        console.print(f"[yellow]Interactive mode unavailable: {e}[/]")
        console.print("[dim]Fallback: use [green]docgen <command>[/] directly[/]")


if __name__ == "__main__":
    _cli_main()
