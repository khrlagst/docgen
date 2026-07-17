import time
import os
import json

import typer
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown
from docgen import __version__
from docgen.config import (
    load_config,
    save_config,
    get_default_config,
    project_config_path,
    load_merged,
    default_model_for,
    MODELS_BY_PROVIDER,
    validate_provider_model,
    CONFIG_KEY_REFERENCE,
    _build_config_set_help,
)
from docgen.cli_complete import (
    complete_providers,
    complete_templates,
    complete_config_keys,
    complete_config_value,
)
from docgen.context.collector import ContextCollector
from docgen.generator.engine import GenerationEngine, GenerationResult, TokenUsage
from docgen.generator.cache import ResponseCache, DEFAULT_CACHE_PATH
from docgen.generator.semantic_cache import SemanticCache
from docgen.llm.factory import ProviderFactory, PROVIDER_REGISTRY
from docgen.llm.errors import format_provider_error_text

PROVIDER_CHOICES = ", ".join(PROVIDER_REGISTRY.keys())
from docgen.welcome import is_onboarded, run_onboarding, show_legal
from docgen.llm.base import LLMConfig
from docgen.output.markdown import write_docs
from docgen.output.pdf import markdown_to_pdf, markdown_to_html

app = typer.Typer(
    name="docgen",
    help="AI-powered documentation generator for solo/indie developers",
    pretty_exceptions_enable=False,
    add_completion=True,
)


def build_llm_config(config: dict) -> LLMConfig:
    """Build an LLMConfig from the user's config, honoring llm.max_tokens.

    If no model is set, a provider-appropriate default is used so onboarding
    without choosing a model still works (e.g. OpenRouter needs the qualified
    `deepseek/deepseek-chat`, not the ambiguous bare `deepseek-chat`).
    """
    from docgen.config import default_model_for

    llm = config.get("llm", {})
    provider = llm.get("provider", "deepseek")
    model = llm.get("model") or default_model_for(provider)
    return LLMConfig(
        api_key=llm.get("api_key", ""),
        base_url=llm.get("base_url", "https://api.deepseek.com"),
        model=model,
        temperature=float(llm.get("temperature", 0.3)),
        max_tokens=int(llm.get("max_tokens", 8192)),
        timeout=float(llm.get("timeout", 120)),
    )


def apply_llm_overrides(config: dict, provider: str | None, model: str | None) -> None:
    """Apply --provider/--model CLI flags on top of the merged config."""
    if provider:
        config.setdefault("llm", {})["provider"] = provider
    if model:
        config.setdefault("llm", {})["model"] = model


def _warn_if_unknown_model(config: dict) -> None:
    """Print a warning (not an error) when the chosen model isn't in the catalog."""
    llm = config.get("llm", {})
    warning = validate_provider_model(
        llm.get("provider", "deepseek"), llm.get("model")
    )
    if warning:
        console.print(f"[yellow]{warning}[/]")


# Where a `docgen models --refresh` result is cached (per user, cross-project).
MODELS_CACHE_PATH = Path("~/.config/docgen/models_cache.json").expanduser()


def _load_cached_models() -> dict:
    try:
        if MODELS_CACHE_PATH.exists():
            return json.loads(MODELS_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cached_models(cache: dict) -> None:
    try:
        MODELS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        MODELS_CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception:
        pass


def _fetch_live_models(provider: str, config: dict) -> list[str] | None:
    """Best-effort live model list for ``provider``. Returns None if it can't be fetched.

    API-key providers use the OpenAI-compatible ``/models`` endpoint; Ollama is
    queried via its local ``/api/tags`` endpoint. Any failure (no key, offline,
    unsupported endpoint) returns None so the caller can fall back to the curated
    catalog.
    """
    from docgen.llm.factory import PROVIDER_REGISTRY

    meta = PROVIDER_REGISTRY.get(provider)
    if meta is None:
        return None

    if meta.get("local"):  # Ollama
        try:
            import urllib.request

            with urllib.request.urlopen(
                "http://localhost:11434/api/tags", timeout=5
            ) as resp:
                data = json.load(resp)
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return None

    llm = config.get("llm", {})
    api_key = llm.get("api_key") or os.getenv(meta.get("auth_env", "") or "", "")
    if not api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url=meta.get("base_url") or llm.get("base_url", ""),
            default_headers=meta.get("default_headers") or {},
        )
        listing = client.models.list()
        return [m.id for m in listing.data]
    except Exception:
        return None


def format_provider_error(e: Exception) -> str:
    """Turn a provider/LLM exception into a concise, colorized message.

    The plain-text logic (per-status explanations, accurate 402 prompt-token
    wording, fix hints) lives in :func:`docgen.llm.errors.format_provider_error_text`
    so the generation engine can reuse it for plain-text warnings. Here we only
    wrap it in Rich markup.
    """
    return f"[red]{format_provider_error_text(e)}[/]"
config_app = typer.Typer(no_args_is_help=True)
app.add_typer(config_app, name="config", help="View/set configuration")

cache_app = typer.Typer(no_args_is_help=True)
app.add_typer(cache_app, name="cache", help="Manage the generation response cache")

console = Console()


class _TokenStatus:
    """Holds the currently active Rich status spinner (if any)."""

    current = None


_token_status = _TokenStatus()


def _resolve_project_path(project_path: Path | str | None, cwd: Path | None = None) -> Path:
    base = (cwd or Path.cwd()).resolve()
    if project_path is None:
        return base

    candidate = Path(project_path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    candidate = candidate.resolve()

    if candidate.exists():
        return candidate
    return candidate


def _detect_source_dir(project_path: Path) -> Path:
    if (project_path / "src").exists():
        return project_path / "src"
    if (project_path / "app").exists():
        return project_path / "app"
    return project_path


def _version_callback(value: bool):
    if value:
        console.print(f"docgen v{__version__}")
        raise typer.Exit()


def _check_first_run(ctx: typer.Context):
    if not ctx.invoked_subcommand:
        from docgen.tui import _cli_main
        _cli_main()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-V", help="Show version and exit", callback=_version_callback
    ),
):
    _check_first_run(ctx)


def _safe_ask(questionary_call):
    """Wrap questionary calls to handle KeyboardInterrupt gracefully."""
    try:
        return questionary_call
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/]")
        raise typer.Exit(1)


def ensure_gitignore(project_path: Path) -> None:
    """Append PROJECT_CONFIG_DIR/ to the project .gitignore so the local
    config (which may hold an API key) is never committed."""
    from docgen.config import PROJECT_CONFIG_DIR

    marker = f"{PROJECT_CONFIG_DIR}/"
    gitignore = project_path / ".gitignore"
    if gitignore.exists():
        lines = gitignore.read_text(encoding="utf-8").splitlines()
        if marker in lines:
            return
        with gitignore.open("a", encoding="utf-8") as f:
            f.write(f"\n# docgen (local config with secrets)\n{marker}\n")
    else:
        gitignore.write_text(
            f"# docgen (local config with secrets)\n{marker}\n", encoding="utf-8"
        )


def watch_source(source_dir: Path, on_change, debounce: float = 0.5):
    """Watch a source directory and call ``on_change(path)`` on relevant edits.

    Ignores directories, dotfiles/ignored paths, and debounces rapid bursts
    (e.g. editor save storms) so a single logical edit fires one regeneration.
    Returns the started ``watchdog`` Observer (call ``.stop()``/``.join()``).
    """
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    class SourceChangeHandler(FileSystemEventHandler):
        def __init__(self, callback, debounce=0.5):
            self.callback = callback
            self.debounce = debounce
            self._last: dict = {}

        def _should_handle(self, event) -> bool:
            if getattr(event, "is_directory", False):
                return False
            src = Path(str(event.src_path))
            if any(part.startswith(".") for part in src.parts):
                return False
            return True

        def _dispatch(self, event):
            if not self._should_handle(event):
                return
            now = time.time()
            key = str(event.src_path)
            if now - self._last.get(key, 0) < self.debounce:
                self._last[key] = now
                return
            self._last[key] = now
            self.callback(str(event.src_path))

        def on_modified(self, event):
            self._dispatch(event)

        def on_created(self, event):
            self._dispatch(event)

        def on_moved(self, event):
            self._dispatch(event)

    observer = Observer()
    observer.schedule(SourceChangeHandler(on_change, debounce), str(source_dir), recursive=True)
    observer.start()
    return observer


@app.command()
def init(
    project_path: Path | None = typer.Argument(
        None,
        help="Path to project root (defaults to the current directory)",
        exists=False,
        file_okay=False,
        dir_okay=True,
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Proceed even if docs/ already exists"
    ),
):
    """Scaffold a new documentation project.

    Runs an interactive wizard to gather project metadata (name, version,
    description, language) and creates the docs/ directory structure.
    """
    from docgen.context.prompts import collect_project_info

    project_path = _resolve_project_path(project_path)
    if not project_path.exists():
        console.print(f"[red]Project path not found: {project_path}[/]")
        raise typer.Exit(1)

    docs_dir = project_path / "docs"

    if docs_dir.exists() and not force:
        console.print(
            "[yellow]docs/ directory already exists. Use --force to proceed.[/]"
        )
        raise typer.Exit(1)

    if not project_path.name or project_path.name == ".":
        project_label = str(project_path)
    else:
        project_label = project_path.name

    console.print(f"[cyan]Using project path:[/] {project_path}")
    info = _safe_ask(collect_project_info())
    info.setdefault("path", str(project_path))
    info["name"] = info.get("name") or project_label
    docs_dir.mkdir(parents=True, exist_ok=True)

    cfg_path = project_config_path(project_path)
    config = load_config(cfg_path)
    config["project"] = info
    save_config(config, cfg_path)
    ensure_gitignore(project_path)

    (docs_dir / "index.md").write_text(
        f"# {info['name']}\n\n{info['description']}\n\n"
        f"<!-- Documentation scaffolded by docgen -->\n"
    )
    (docs_dir / ".gitkeep").write_text("")

    console.print(f"[green]Scaffolded documentation at {docs_dir}[/]")
    console.print(f"[dim]Run 'docgen generate' to populate with AI-generated content[/]")


@app.command()
def generate(
    output_dir: Path | None = typer.Option(
        None, "--output", "-o", help="Output directory for generated docs"
    ),
    template: str = typer.Option(
        "wiki", "--template", "-t", help="Template style: wiki, manual, or readme",
        autocompletion=complete_templates,
    ),
    source_dir: Path | None = typer.Option(
        None, "--source", "-s", help="Source code directory to analyze"
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Skip the response cache and force regeneration"
    ),
    semantic: bool | None = typer.Option(
        None,
        "--semantic-cache/--no-semantic-cache",
        help="Use the semantic cache (near-duplicate prompts). Default: config",
    ),
    prompt_tokens_limit: int | None = typer.Option(
        None,
        "--prompt-tokens-limit",
        help="Max tokens sent per LLM request (default 20000). Lower it if your "
        "provider/key rejects oversized prompts.",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help=f"LLM provider to use (overrides config). One of: {PROVIDER_CHOICES}",
        autocompletion=complete_providers,
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Model ID for the provider (overrides config). See `docgen models --provider <provider>`",
    ),
):
    """Generate documentation using AI.

    Scans source code, sends it to the LLM along with project metadata,
    and produces formatted documentation pages using Jinja2 templates.
    Supports Python, JavaScript, TypeScript, HTML, and many more languages.
    """
    config = load_config()
    resolved_project_path = _resolve_project_path(config.get("project", {}).get("path"), cwd=Path.cwd())
    config = load_merged(resolved_project_path)
    apply_llm_overrides(config, provider, model)
    _warn_if_unknown_model(config)
    cfg_write = project_config_path(resolved_project_path)

    if not is_onboarded(config) and not run_onboarding(cfg_write):
        raise typer.Exit(1)
    source_dir = _detect_source_dir(resolved_project_path if source_dir is None else _resolve_project_path(source_dir, cwd=Path.cwd()))
    output_dir = _resolve_project_path(output_dir or Path("docs"), cwd=resolved_project_path)

    if not source_dir.exists():
        console.print(f"[yellow]Source directory not found: {source_dir}[/]")
        console.print("[yellow]Continuing with project metadata only...[/]")
    if not config.get("project"):
        console.print(
            "[red]No project configured. Run 'docgen init' first.[/]"
        )
        raise typer.Exit(1)

    run_generation(
        source_dir,
        output_dir,
        template,
        config,
        no_cache=no_cache,
        semantic=semantic,
        prompt_tokens_limit=prompt_tokens_limit,
    )


def run_generation(
    source_dir: Path,
    output_dir: Path,
    template: str,
    config: dict,
    no_cache: bool = False,
    show_status: bool = True,
    semantic: bool | None = None,
    prompt_tokens_limit: int | None = None,
) -> "GenerationResult":
    """Run the full generation pipeline and write docs to ``output_dir``.

    Shared by `generate` and the `serve --watch` source watcher so a source
    change regenerates the docs with the same pipeline (reusing the cache for
    unchanged content).
    """
    from contextlib import contextmanager

    @contextmanager
    def _status(msg):
        if show_status:
            with console.status(f"[bold green]{msg}") as s:
                _token_status.current = s
                try:
                    yield
                finally:
                    _token_status.current = None
        else:
            yield

    def _on_token_progress(u: TokenUsage) -> None:
        s = _token_status.current
        if s is not None:
            s.update(
                f"[bold green]AI is generating documentation... "
                f"[cyan]{u.total_tokens:,} tokens[/] "
                f"[dim]({u.provider_calls} calls, {u.cached_calls} cached)[/]"
            )

    with _status("Collecting project context..."):
        collector = ContextCollector(source_dir if source_dir.exists() else None)
        context = collector.collect(config["project"])

    llm_config = build_llm_config(config)

    if not llm_config.api_key:
        console.print(
            "[red]No LLM API key configured. Set DOCGEN_API_KEY or run "
            "'docgen config set llm.api_key <key>'[/]"
        )
        raise typer.Exit(1)

    provider = ProviderFactory.create(
        config.get("llm", {}).get("provider", "deepseek"), llm_config
    )

    gen_cfg = config.get("generation", {})
    cache_enabled = bool(gen_cfg.get("cache", True)) and not no_cache
    cache = ResponseCache(enabled=cache_enabled) if cache_enabled else None
    cache_prefix = f"{config.get('llm', {}).get('provider', 'deepseek')}:{llm_config.model}"

    if semantic is None:
        semantic = bool(gen_cfg.get("semantic_cache", False))
    semantic_cache = None
    if semantic:
        semantic_cache = SemanticCache(
            store_path=DEFAULT_CACHE_PATH.parent / "semantic.jsonl", enabled=True
        )

    if prompt_tokens_limit is None:
        prompt_tokens_limit = gen_cfg.get("prompt_tokens_limit")
    body_preview_lines = int(gen_cfg.get("api_body_preview_lines", 15))

    user_template_dir = config.get("templates", {}).get("directory")
    engine = GenerationEngine(
        provider,
        template_name=template,
        user_template_dir=user_template_dir,
        cache=cache,
        cache_prefix=cache_prefix,
        semantic_cache=semantic_cache,
        on_progress=_on_token_progress if show_status else None,
        prompt_tokens_limit=prompt_tokens_limit,
        body_preview_lines=body_preview_lines,
    )

    try:
        with _status("AI is generating documentation..."):
            result = engine.generate(context)
    except Exception as e:
        console.print(format_provider_error(e))
        raise typer.Exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_docs(output_dir, result.files)
    console.print(f"[green]Documentation generated in {output_dir}/[/]")
    u = result.token_usage
    console.print(
        f"[cyan]Used {u.total_tokens:,} tokens[/] "
        f"[dim]({u.prompt_tokens:,} prompt + {u.completion_tokens:,} completion; "
        f"{u.provider_calls} API calls, {u.cached_calls} from cache)[/]"
    )

    for filepath in result.files:
        console.print(f"  [dim]created[/] {output_dir / filepath}")

    if result.warnings:
        for warning in result.warnings:
            console.print(f"[yellow]Warning: {warning}[/]")

    if cache is not None and (cache.hits or cache.misses):
        console.print(
            f"[dim]Cache: {cache.hits} served from cache, "
            f"{cache.misses} generated by AI.[/]"
        )
    return result


@app.command()
def refine(
    section: str = typer.Argument(
        ..., help="Path to markdown file to improve"
    ),
    instruction: str = typer.Option(
        "Improve clarity, fix grammar, and add examples",
        "--prompt",
        "-p",
        help="What to improve",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help=f"LLM provider to use (overrides config). One of: {PROVIDER_CHOICES}",
        autocompletion=complete_providers,
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Model ID for the provider (overrides config). See `docgen models --provider <provider>`",
    ),
):
    """Improve a specific documentation section with AI.

    Sends the current markdown file to the LLM with your instructions,
    shows a diff of the changes, and asks for confirmation before saving.
    A .bak backup is created automatically.
    """
    from questionary import confirm

    section_path = Path(section)
    if not section_path.exists():
        console.print(f"[red]File not found: {section}[/]")
        raise typer.Exit(1)

    original = section_path.read_text(encoding="utf-8")
    config = load_merged(Path.cwd())
    apply_llm_overrides(config, provider, model)
    _warn_if_unknown_model(config)
    cfg_write = project_config_path(Path.cwd())

    if not is_onboarded(config) and not run_onboarding(cfg_write):
        raise typer.Exit(1)

    llm_config = build_llm_config(config)

    if not llm_config.api_key:
        console.print("[red]No LLM API key configured.[/]")
        raise typer.Exit(1)

    provider = ProviderFactory.create(
        config.get("llm", {}).get("provider", "deepseek"), llm_config
    )

    try:
        with console.status("[bold green]Refining..."):
            improved = provider.generate(
                "You are a documentation editor. Improve the given documentation section.",
                f"## Instruction\n{instruction}\n\n## Current Content\n{original}",
            ).content
    except Exception as e:
        console.print(format_provider_error(e))
        raise typer.Exit(1)

    import difflib

    diff = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        improved.splitlines(keepends=True),
        fromfile="original",
        tofile="improved",
        n=3,
    ))
    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

    console.print(f"\n[bold]Changes:[/] [green]+{added}[/] [red]-{removed}[/] lines\n")
    if added + removed < 50:
        for line in diff:
            if line.startswith("+"):
                console.print(f"[green]{line.rstrip()}[/]")
            elif line.startswith("-"):
                console.print(f"[red]{line.rstrip()}[/]")
            elif line.startswith("@@"):
                console.print(f"[cyan]{line.rstrip()}[/]")
    else:
        console.print(Markdown(improved))

    if _safe_ask(confirm("Apply these changes?")):
        backup = section_path.with_suffix(section_path.suffix + ".bak")
        backup.write_text(original, encoding="utf-8")
        section_path.write_text(improved, encoding="utf-8")
        console.print(f"[green]Section updated! Backup saved as {backup.name}[/]")


def _build_preview_server(docs_dir: Path, port: int):
    """Create the preview HTTP server (threaded, signal-friendly, reusable port).

    `ThreadingHTTPServer` + `daemon_threads` keeps the accept loop in its own
    thread, so a slow or keep-alive request can never block signal delivery
    (Ctrl+C). The caller drives shutdown via ``server.shutdown()`` from the main
    thread.
    """
    import http.server

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(docs_dir), **kwargs)

        def do_GET(self):
            parsed = self.path.split("?", 1)[0]
            if parsed in {"/", "/index.html"}:
                index_path = docs_dir / "index.md"
                if index_path.exists():
                    from docgen.output.markdown import build_docs_landing_page

                    body = build_docs_landing_page(docs_dir).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

            normalized = parsed.rstrip("/") or "/"
            if normalized != "/":
                relative_path = normalized.lstrip("/")
                if not relative_path.endswith(".md"):
                    relative_path = f"{relative_path}.md"
                markdown_path = docs_dir / relative_path
                if markdown_path.exists():
                    from docgen.output.markdown import build_markdown_page

                    body = build_markdown_page(docs_dir, relative_path).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

            super().do_GET()

        def log_message(self, format, *args):
            pass

    server = http.server.ThreadingHTTPServer(("", port), Handler)
    server.daemon_threads = True
    server.allow_reuse_address = True
    return server


@app.command()
def serve(
    port: int = typer.Option(8000, "--port", "-p", help="Port to serve on"),
    docs_dir: Path = typer.Option(
        "docs", "--docs-dir", "-d", help="Documentation directory"
    ),
    source: Path | None = typer.Option(
        None, "--source", "-s", help="Source directory to watch and regenerate from"
    ),
    template: str = typer.Option(
        "wiki", "--template", "-t", help="Template style: wiki, manual, or readme",
        autocompletion=complete_templates,
    ),
    watch: bool = typer.Option(
        False, "--watch", "-w", help="Auto-regenerate docs on source changes"
    ),
):
    """Preview documentation locally.

    Starts a local HTTP server to preview your generated documentation
    in a web browser. With --watch, edits to your source tree regenerate
    the docs automatically (the server reads files fresh on each request).
    """
    import http.server
    import threading

    docs_dir = docs_dir.resolve()
    if not docs_dir.exists():
        console.print(f"[red]Directory not found: {docs_dir}[/]")
        raise typer.Exit(1)

    observer = None
    if watch:
        source_dir = source.resolve() if source else _detect_source_dir(Path.cwd())
        cfg = load_merged(Path.cwd())
        if not is_onboarded(cfg) or not source_dir.exists():
            console.print(
                "[yellow]Watch regeneration requires an onboarded project and a "
                "source directory. Serving docs without auto-regeneration.[/]"
            )
        else:

            def _regenerate_worker(changed_path: str):
                try:
                    console.print(
                        f"[dim]Source change: {Path(changed_path).name} — "
                        "regenerating docs...[/]"
                    )
                    run_generation(
                        source_dir, docs_dir, template, cfg, show_status=False
                    )
                    console.print("[green]Docs regenerated.[/]")
                except BaseException as exc:  # keep the preview server alive
                    console.print(f"[red]Regeneration failed: {exc}[/]")

            def _regenerate(changed_path: str):
                # Run in a daemon thread so a slow LLM regeneration never blocks
                # the observer thread (which would otherwise hang shutdown on
                # Ctrl+C while observer.join() waits for the in-flight callback).
                threading.Thread(
                    target=_regenerate_worker, args=(changed_path,), daemon=True
                ).start()

            observer = watch_source(source_dir, _regenerate)
            console.print(
                f"[green]Source watching enabled (watching {source_dir})[/]"
            )

    server = _build_preview_server(docs_dir, port)

    try:
        console.print(f"[green]Serving docs at http://localhost:{port}[/]")
        console.print(f"[dim]Directory: {docs_dir}[/]")
        if watch:
            console.print("[dim]Watching for changes... (Ctrl+C to stop)[/]")
        else:
            console.print("[dim]Press Ctrl+C to stop[/]")
        # Run in the main thread: ThreadingHTTPServer handles each request in its
        # own (daemon) thread, so the main thread only does the accept/poll loop
        # (0.5s poll interval). That keeps SIGINT (Ctrl+C) deliverable, unlike a
        # single-threaded server whose main thread blocks on a keep-alive read.
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[yellow]Server stopped.[/]")
    finally:
        server.shutdown()
        server.server_close()
        if observer is not None:
            observer.stop()
            observer.join(timeout=2.0)


@app.command()
def export(
    source: Path = typer.Argument(
        "docs", help="Source markdown directory", exists=True, file_okay=False
    ),
    output: Path = typer.Argument(
        "docs.pdf", help="Output PDF file"
    ),
    engine: str = typer.Option(
        "weasyprint", "--engine", "-e", help="PDF engine (weasyprint or pandoc)"
    ),
):
    """Export markdown documentation to PDF.

    Combines all markdown files in logical order, converts to HTML,
    then renders a PDF with professional CSS styling. Supports
    WeasyPrint (default) or Pandoc as the rendering engine.
    """
    source = source.resolve()
    output = output.resolve()

    try:
        with console.status(f"[bold green]Converting to PDF using {engine}..."):
            markdown_to_pdf(source, output, engine=engine)
    except ImportError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1)

    console.print(f"[green]PDF generated: {output}[/]")


@app.command()
def html(
    source: Path = typer.Argument(
        "docs", help="Source markdown directory", exists=True, file_okay=False
    ),
    output: Path = typer.Argument(
        "docs.html", help="Output HTML file"
    ),
):
    """Export documentation as a single self-contained HTML file.

    Combines all markdown pages, renders them to HTML with embedded
    CSS styling, and produces one portable HTML file ready to share.
    """
    source = source.resolve()
    output = output.resolve()

    try:
        with console.status("[bold green]Generating HTML..."):
            html_content = markdown_to_html(source)
    except ImportError as e:
        console.print(
            f"[red]Missing dependency: {e}. "
            "The HTML export needs the 'markdown' package (pip install markdown).[/]"
        )
        raise typer.Exit(1)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_content, encoding="utf-8")
    console.print(f"[green]HTML generated: {output}[/]")


@app.command()
def site(
    source: Path = typer.Argument(
        "docs", help="Source markdown directory", exists=True, file_okay=False
    ),
    output: Path = typer.Argument(
        ".", help="Output directory for MkDocs site"
    ),
):
    """Generate a MkDocs site configuration from generated docs.

    Creates a ready-to-use mkdocs.yml with Material theme, dark/light
    mode toggle, search, and navigation structure based on your pages.
    Run 'mkdocs serve' in the output directory to preview.
    """
    source = source.resolve()
    output = output.resolve()

    config = load_merged(Path.cwd())
    project = config.get("project", {})
    files = []

    for md_file in sorted(source.rglob("*.md")):
        title = md_file.stem.replace("-", " ").replace("_", " ").title()
        rel = str(md_file.relative_to(source))
        files.append({"title": title, "file": rel})

    from docgen.generator.mkdocs import generate_mkdocs_config

    yml = generate_mkdocs_config(
        project_name=project.get("name", "Project"),
        description=project.get("description", ""),
        author=project.get("author", ""),
        repo=project.get("repo", ""),
        files=files,
    )

    output.mkdir(parents=True, exist_ok=True)
    (output / "mkdocs.yml").write_text(yml, encoding="utf-8")

    console.print(f"[green]MkDocs config generated: {output / 'mkdocs.yml'}[/]")
    console.print("[dim]Run 'mkdocs serve' to preview the site[/]")


@config_app.command()
def validate():
    """Check configuration for common issues.

    Verifies: project config exists, API key is set, provider is
    configured, template files are found, and PDF dependencies are
    installed. Reports each check as OK, FAIL, or WARN.
    """
    import shutil

    ok = True

    cfg = load_merged(Path.cwd())
    if not cfg:
        console.print("[yellow]No configuration found. Run 'docgen init' first.[/]")
        ok = False

    project = cfg.get("project")
    if project:
        console.print(f"[green]OK[/] Project configured: [cyan]{project.get('name')}[/]")
    else:
        console.print("[red]FAIL[/] No project configured. Run [bold]docgen init[/]")
        ok = False

    llm_config = cfg.get("llm", {})
    api_key = llm_config.get("api_key", "")
    if api_key:
        masked = api_key[:4] + "****" + api_key[-4:]
        console.print(f"[green]OK[/] LLM API key set: [cyan]{masked}[/]")
    else:
        console.print(
            "[red]FAIL[/] No LLM API key. Set [bold]DOCGEN_API_KEY[/] or run [bold]docgen config set llm.api_key <key>[/]"
        )
        ok = False

    provider = llm_config.get("provider", "deepseek")
    if provider in PROVIDER_REGISTRY:
        console.print(f"[green]OK[/] LLM provider: [cyan]{provider}[/]")
    else:
        console.print(
            f"[red]FAIL[/] LLM provider [cyan]{provider}[/] is not supported. "
            f"Supported: {', '.join(PROVIDER_REGISTRY.keys())}"
        )
        ok = False
    effective_model = llm_config.get("model") or default_model_for(provider)
    console.print(f"[green]OK[/] Model: [cyan]{effective_model}[/]")

    template = cfg.get("templates", {}).get("default", "wiki")
    template_dir = Path(__file__).parent / "templates" / template
    if template in ("wiki", "manual", "readme"):
        console.print(f"[green]OK[/] Template [cyan]{template}[/]")
    else:
        console.print(
            f"[red]FAIL[/] Template [cyan]{template}[/] is not a built-in style "
            "(choose wiki, manual, or readme)"
        )
        ok = False
    if template_dir.exists():
        console.print(f"[green]OK[/] Template dir [cyan]{template}[/] found")
    else:
        console.print(f"[red]FAIL[/] Template dir [cyan]{template}[/] not found")
        ok = False

    user_dir = cfg.get("templates", {}).get("directory")
    if user_dir and Path(user_dir).exists():
        console.print(f"[green]OK[/] User template dir: [cyan]{user_dir}[/]")

    pdf_engine = cfg.get("export", {}).get("pdf_engine", "weasyprint")
    if pdf_engine == "weasyprint":
        try:
            import weasyprint
            console.print("[green]OK[/] PDF engine: [cyan]weasyprint[/] (installed)")
        except (ImportError, OSError):
            console.print(
                "[yellow]WARN[/] PDF engine: [cyan]weasyprint[/] (not installed. Run [bold]pip install docgen[pdf][/])"
            )
    elif pdf_engine == "pandoc":
        if shutil.which("pandoc"):
            console.print("[green]OK[/] PDF engine: [cyan]pandoc[/] (found)")
        else:
            console.print(
                "[yellow]WARN[/] PDF engine: [cyan]pandoc[/] (not found in PATH. Install from https://pandoc.org)"
            )

    if ok:
        console.print("\n[bold green]All checks passed! Configuration looks good.[/]")
    else:
        console.print("\n[yellow]Fix the issues above, then run again.[/]")
        raise typer.Exit(1)


config_app.command(name="check")(validate)


@cache_app.command("clear")
def cache_clear():
    """Delete all cached AI responses."""
    cache = ResponseCache(enabled=True)
    cache.clear()
    console.print("[green]Generation cache cleared.[/]")


@app.command()
def legal():
    """Show the Terms of Service and Privacy Policy."""
    show_legal()


@app.command()
def providers():
    """List the LLM providers docgen supports."""
    console.print("[bold]Supported LLM providers[/]")
    for name, meta in PROVIDER_REGISTRY.items():
        kind = "local" if meta.get("local") else "API key"
        console.print(f"  [cyan]{name}[/] — {meta['display']} ({kind})")


@app.command()
def models(
    provider: str = typer.Option(
        None,
        "--provider",
        "-p",
        help=f"Filter the list to one provider. One of: {PROVIDER_CHOICES}",
        autocompletion=complete_providers,
    ),
    list_providers: bool = typer.Option(
        False,
        "--providers",
        help="List the supported providers instead of models (alias for `docgen providers`)",
    ),
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help="Fetch live model lists from the providers (needs API key / local server)",
    ),
):
    """List model IDs per provider.

    Without --refresh, shows the curated catalog (or a previously cached
    refresh). With --refresh, fetches live lists from each provider's API and
    caches them.
    """
    if list_providers:
        console.print("[bold]Supported LLM providers[/]")
        for name, meta in PROVIDER_REGISTRY.items():
            kind = "local" if meta.get("local") else "API key"
            console.print(f"  [cyan]{name}[/] — {meta['display']} ({kind})")
        return

    if provider and provider not in MODELS_BY_PROVIDER:
        console.print(f"[red]Unknown provider: {provider}[/]")
        raise typer.Exit(1)

    config = load_config()
    cache = _load_cached_models()
    targets = [provider] if provider else list(MODELS_BY_PROVIDER.keys())

    for name in targets:
        if refresh:
            live = _fetch_live_models(name, config)
            if live is None:
                console.print(
                    f"[yellow]Could not fetch live models for {name}; "
                    f"showing curated list.[/]"
                )
                listing = MODELS_BY_PROVIDER.get(name, [])
                source = "curated"
            else:
                listing = live
                source = "live"
                cache[name] = listing
        elif name in cache and cache[name]:
            listing = cache[name]
            source = "cached"
        else:
            listing = MODELS_BY_PROVIDER.get(name, [])
            source = "curated"

        label = f"[bold]{name}[/]"
        if source != "curated":
            label += f" [dim]({source})[/]"
        console.print(label)
        if not listing:
            console.print(
                "  [dim](arbitrary names — set the model ID directly, e.g. "
                "your Azure deployment or a local Ollama tag)[/]"
            )
            continue
        for m in listing:
            console.print(f"  [cyan]{m}[/]")

    if refresh:
        _save_cached_models(cache)


@app.command()
def setup():
    """Run first-time setup: choose provider, API key, and accept terms."""
    if not run_onboarding():
        raise typer.Exit(1)


@config_app.command()
def show():
    """Show current configuration."""
    cfg = load_merged(Path.cwd())
    if not cfg:
        console.print("[yellow]No configuration found. Using defaults.[/]")
        cfg = get_default_config()

    for section, values in cfg.items():
        if section == "_meta":
            continue
        console.print(f"\n[bold]{section}[/]")
        if isinstance(values, dict):
            for key, value in values.items():
                full_key = f"{section}.{key}"
                ref = CONFIG_KEY_REFERENCE.get(full_key)
                if ref and ref.get("type") == "secret" and value:
                    value = "****" + value[-4:]
                console.print(f"  {key}: [cyan]{value}[/]")
        else:
            console.print(f"  {values}")


NUMERIC_KEYS = {"temperature", "timeout", "max_tokens", "port"}


@config_app.command(help=_build_config_set_help())
def set(
    key: str = typer.Argument(..., help="Config key (e.g. llm.provider)", autocompletion=complete_config_keys),
    value: str = typer.Argument(..., help="Value for the key", autocompletion=complete_config_value),
):
    """Set a configuration value (e.g., llm.model deepseek-chat)."""
    cfg = load_merged(Path.cwd())
    if not cfg:
        cfg = get_default_config()

    parts = key.split(".")
    target = cfg
    for part in parts[:-1]:
        if part not in target:
            target[part] = {}
        target = target[part]

    last_key = parts[-1]
    ref = CONFIG_KEY_REFERENCE.get(key)
    if ref:
        type_name = ref.get("type")
        if type_name == "bool":
            if value.lower() not in ("true", "false"):
                console.print(
                    f"[yellow]'{key}' expects true/false, not '{value}'. "
                    "Value stored as-is; set true or false to enable/disable.[/]"
                )
            target[last_key] = value.lower() == "true"
        elif type_name == "int":
            try:
                target[last_key] = int(value)
            except ValueError:
                console.print(
                    f"[yellow]'{key}' expects an integer, not '{value}'. Stored as-is.[/]"
                )
                target[last_key] = value
        elif type_name == "float":
            try:
                target[last_key] = float(value)
            except ValueError:
                console.print(
                    f"[yellow]'{key}' expects a number, not '{value}'. Stored as-is.[/]"
                )
                target[last_key] = value
        elif type_name == "choice" and ref.get("choices"):
            if value not in ref["choices"]:
                console.print(
                    f"[red]Invalid value for '{key}': '{value}'. "
                    f"Choose one of: {', '.join(ref['choices'])}.[/]"
                )
                raise typer.Exit(1)
            target[last_key] = value
        else:
            target[last_key] = value
    else:
        if last_key in NUMERIC_KEYS:
            try:
                if "." in value:
                    target[last_key] = float(value)
                else:
                    target[last_key] = int(value)
            except ValueError:
                target[last_key] = value
        elif value.lower() in ("true", "false"):
            target[last_key] = value.lower() == "true"
        else:
            target[last_key] = value
        console.print(
            f"[yellow]Unknown config key '{key}'. Valid keys:[/] "
            + ", ".join(CONFIG_KEY_REFERENCE.keys())
        )

    save_config(cfg, project_config_path(Path.cwd()))
    console.print(f"[green]Set {key} = {target[last_key]}[/]")


@config_app.command()
def keys():
    """List all known configuration keys and their allowed values."""
    from rich.table import Table

    table = Table(title="Known configuration keys")
    table.add_column("Key", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Default", style="green")
    table.add_column("Allowed values / notes")
    for key, ref in CONFIG_KEY_REFERENCE.items():
        allowed = ", ".join(ref["choices"]) if ref.get("choices") else ref["description"]
        table.add_row(
            key,
            ref["type"],
            str(ref.get("default", "—")),
            allowed,
        )
    console.print(table)


if __name__ == "__main__":
    app()
