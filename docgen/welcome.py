from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

LOGO = r"""
╔═════════════════════════════════════════════════════════════════════════════════════╗
║                    ___           ___           ___           ___           ___      ║
║     _____         /\  \         /\__\         /\__\         /\__\         /\  \     ║
║    /::\  \       /::\  \       /:/  /        /:/ _/_       /:/ _/_        \:\  \    ║
║   /:/\:\  \     /:/\:\  \     /:/  /        /:/ /\  \     /:/ /\__\        \:\  \   ║
║  /:/  \:\__\   /:/  \:\  \   /:/  /  ___   /:/ /::\  \   /:/ /:/ _/_   _____\:\  \  ║
║ /:/__/ \:|__| /:/__/ \:\__\ /:/__/  /\__\ /:/__\/\:\__\ /:/_/:/ /\__\ /::::::::\__\ ║
║ \:\  \ /:/  / \:\  \ /:/  / \:\  \ /:/  / \:\  \ /:/  / \:\/:/ /:/  / \:\~~\~~\/__/ ║
║  \:\  /:/  /   \:\  /:/  /   \:\  /:/  /   \:\  /:/  /   \::/_/:/  /   \:\  \       ║
║   \:\/:/  /     \:\/:/  /     \:\/:/  /     \:\/:/  /     \:\/:/  /     \:\  \      ║
║    \::/  /       \::/  /       \::/  /       \::/  /       \::/  /       \:\__\     ║
║     \/__/         \/__/         \/__/         \/__/         \/__/         \/__/     ║
║                                                                                     ║
║                                       v.0.1.0                                       ║
║                                                                                     ║
║                                AI Documentation Forge                               ║
╚═════════════════════════════════════════════════════════════════════════════════════╝
"""

WELCOME = """
Type help for commands, exit to quit.

[dim]Examples:[/]
  [green]docgen init[/]      -- set up a new documentation project
  [green]docgen generate[/]  -- generate docs from your codebase
  [green]docgen serve[/]     -- preview docs locally
"""

FIRST_RUN_MARKER = "first_run_v1"


def is_first_run() -> bool:
    from docgen.config import load_config, save_config

    cfg = load_config()
    if cfg.get("_meta", {}).get("first_run") == FIRST_RUN_MARKER:
        return False

    if "_meta" not in cfg:
        cfg["_meta"] = {}
    cfg["_meta"]["first_run"] = FIRST_RUN_MARKER
    save_config(cfg)
    return True


def show_welcome():
    console = Console()
    panel = Panel(
        LOGO.strip("\n"),
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(panel)
    console.print(WELCOME)


TERMS_VERSION = "2024-01-01"

TERMS_TEXT = f"""# Terms of Service

**Version:** {TERMS_VERSION}

1. **Acceptance.** By using DocGen you agree to these terms.
2. **What DocGen does.** DocGen reads the source code and metadata of the project you point it at and sends that content to the AI provider you select, via that provider's API, in order to generate documentation.
3. **Your responsibility.** You are responsible for:
   - Having the right to process the code you submit.
   - Complying with your AI provider's own terms of service.
   - Not submitting secrets (API keys, credentials, tokens). DocGen does **not** scan for or redact secrets.
4. **No warranty.** DocGen is provided "as is", without warranty of any kind.
5. **Changes.** These terms may be updated; if the version changes, DocGen will ask you to accept again.
"""

PRIVACY_TEXT = f"""# Privacy Policy

**Version:** {TERMS_VERSION}

1. **Data we send.** To generate docs, DocGen transmits your selected project's source code, file structure, and project metadata to the AI provider you choose.
2. **How providers use it — read this carefully.** DocGen itself does **not** train any model and sends your data only to the provider you configure. However:
   - **Free or third-party models** (including some offered through DeepSeek/OpenRouter free tiers) may **use submitted data to train or improve their models**.
   - **Paid plans** and **self-hosted providers (e.g. Ollama running locally)** generally do **not** use your data for training.
   - Review your provider's privacy policy before use. For sensitive or proprietary code, prefer a paid plan or run a local model with Ollama.
3. **Local storage.** DocGen stores your configuration — provider choice, API base URL, and API key — **locally** in `~/.config/docgen/config.toml`. It is never sent anywhere except to the provider you configure.
4. **No telemetry.** DocGen itself does not collect analytics or phone home.
5. **Your control.** Run `docgen cache clear` to remove cached AI responses, and delete the config file to remove your key.
"""


def _safe_ask(call):
    """Wrap questionary calls to handle KeyboardInterrupt/Cancellation gracefully."""
    try:
        return call
    except KeyboardInterrupt:
        Console().print("\n[yellow]Cancelled.[/]")
        raise SystemExit(1)


def _load_meta() -> dict:
    from docgen.config import load_config

    return load_config().get("_meta", {})


def is_onboarded(config: dict | None = None) -> bool:
    """True once the user has accepted the current ToS/Privacy version.

    Accepts an already-loaded config dict (project-aware) or falls back to
    the global config file.
    """
    meta = _load_meta() if config is None else config.get("_meta", {})
    return bool(meta.get("accepted_terms")) and meta.get("terms_version") == TERMS_VERSION


def show_legal():
    """Print the Terms of Service and Privacy Policy, plus current accept status."""
    console = Console()
    console.print(Panel(Markdown(TERMS_TEXT), title="Terms of Service", border_style="yellow"))
    console.print(Panel(Markdown(PRIVACY_TEXT), title="Privacy Policy", border_style="yellow"))
    meta = _load_meta()
    if meta.get("accepted_terms") and meta.get("terms_version") == TERMS_VERSION:
        console.print("[green]You have accepted the current Terms and Privacy Policy.[/]")
    else:
        console.print("[yellow]You have NOT yet accepted the Terms and Privacy Policy.[/]")


def run_onboarding(
    config_path: Path | None = None, interactive: bool = False
) -> bool:
    """Interactive first-run setup: provider, API key, and consent.

    Writes to the project-local config when `config_path` is given
    (so the key lands in .docgen/, which init adds to .gitignore),
    otherwise to the global config.

    When `interactive` is True the closing tip uses the bare command form
    (e.g. `config set`) suitable for the interactive REPL; otherwise it uses
    the full `docgen <command>` form for standalone use.

    Returns True if setup completed and terms were accepted, False otherwise.
    """
    from docgen.config import load_config, save_config
    from questionary import select, text, password, confirm, Choice

    console = Console()
    console.print()
    console.print(Panel("Welcome to DocGen — let's get you set up.", border_style="cyan"))
    console.print(
        "[dim]DocGen reads your codebase and sends it to an AI provider to generate docs.[/]"
    )

    cfg = load_config(config_path) if config_path else load_config()
    llm = cfg.setdefault("llm", {})

    from docgen.llm.factory import PROVIDER_REGISTRY
    from docgen.config import MODELS_BY_PROVIDER, default_model_for

    provider_choices = [
        Choice(title=f"{meta['display']} ({name})", value=name)
        for name, meta in PROVIDER_REGISTRY.items()
    ]
    provider = _safe_ask(
        select("Choose your AI provider:", choices=provider_choices).ask()
    )
    llm["provider"] = provider

    pmeta = PROVIDER_REGISTRY[provider]
    if pmeta.get("local"):
        default_url = llm.get("base_url", "http://localhost:11434/v1")
        base_url = _safe_ask(text("Ollama base URL:", default=default_url).ask())
        llm["base_url"] = base_url
        llm["api_key"] = "ollama"
    else:
        default_url = pmeta.get("base_url") or llm.get("base_url", "")
        base_url = _safe_ask(text("API base URL:", default=default_url).ask())
        llm["base_url"] = base_url
        api_key = _safe_ask(password("API key (input is hidden):").ask())
        if not api_key:
            console.print("[red]An API key is required for this provider.[/]")
            return False
        llm["api_key"] = api_key

    # Model selection from the curated catalog (falls back to free text when a
    # provider uses arbitrary names, e.g. Azure deployments / Ollama tags).
    catalog = MODELS_BY_PROVIDER.get(provider)
    if catalog:
        llm["model"] = _safe_ask(
            select("Choose a model:", choices=[Choice(title=m, value=m) for m in catalog]).ask()
        )
    else:
        llm["model"] = _safe_ask(
            text("Model ID:", default=default_model_for(provider)).ask()
        )
    console.print()
    console.print(Panel(Markdown(TERMS_TEXT), title="Terms of Service", border_style="yellow"))
    console.print(Panel(Markdown(PRIVACY_TEXT), title="Privacy Policy", border_style="yellow"))

    accepted = _safe_ask(
        confirm("Do you accept the Terms of Service and Privacy Policy?", default=False).ask()
    )
    if not accepted:
        console.print(
            "[red]You must accept the Terms and Privacy Policy to use DocGen.[/]"
        )
        return False

    meta = cfg.setdefault("_meta", {})
    meta["accepted_terms"] = True
    meta["terms_version"] = TERMS_VERSION
    if config_path is not None:
        save_config(cfg, config_path)
    else:
        save_config(cfg)

    config_tip = "config set" if interactive else "docgen config set"
    setup_tip = "setup" if interactive else "docgen setup"
    console.print(
        "[green]Setup complete![/] You can change providers later with "
        f"[bold]{config_tip}[/] or re-run [bold]{setup_tip}[/]."
    )
    return True
