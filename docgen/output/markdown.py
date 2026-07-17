import re
from html import escape
from pathlib import Path


def write_docs(output_dir: Path, files: dict[str, str]):
    """Write generated markdown files to disk."""
    for relative_path, content in files.items():
        target = output_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _escape_html(text: str) -> str:
    """Escape markdown content before embedding it into HTML."""
    return escape(text, quote=True).replace("&#x27;", "&#39;")


def _normalize_inline_lists(markdown_text: str) -> str:
    """Best-effort fix for LLM output that emits run-on bullet lists.

    Some generated docs describe a list inline on a single line, e.g.
    ``The architecture consists of: - A - B - C``. Markdown only treats ``- ``
    as a list item when each item starts on its own line, so the run-on form
    renders as a single paragraph. Split those runs into real list items while
    leaving fenced code, existing lists, tables, and headings untouched.
    """
    lines = markdown_text.split("\n")
    out = []
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue

        stripped = line.lstrip()
        if stripped.startswith(("- ", "* ", "+ ", "#", "|", ">", "<")):
            out.append(line)
            continue

        if " - " in line:
            parts = line.split(" - ")
            if len(parts) >= 3 and all(
                re.match(r"^(\*\*|`|[A-Z0-9])", p.strip()) for p in parts[1:]
            ):
                prefix = parts[0].rstrip()
                items = "\n".join("- " + p.strip() for p in parts[1:])
                out.append(prefix + "\n\n" + items if prefix else items)
                continue

        out.append(line)
    return "\n".join(out)


def _collapse_table_cells(markdown_text: str) -> str:
    """Join multi-line table rows into single lines.

    The markdown table extension only supports one row per line, but generated
    docs sometimes spill a long cell (e.g. a wrapped docstring) onto following
    lines, breaking the table into raw paragraphs. Reassemble any row that starts
    with ``|`` but does not yet end with ``|`` by appending subsequent lines until
    a closing ``|`` is found. This keeps already-generated docs rendering as
    proper tables in the preview without requiring regeneration.
    """
    lines = markdown_text.split("\n")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.lstrip().startswith("|") and not line.rstrip().endswith("|"):
            buf = [line]
            j = i + 1
            closed = False
            while j < n:
                nxt = lines[j]
                buf.append(nxt)
                if nxt.rstrip().endswith("|"):
                    closed = True
                    break
                if nxt.strip() and (
                    nxt.lstrip().startswith("|")
                    or nxt.lstrip().startswith(("#", ">", "```", "<"))
                ):
                    break
                j += 1
            if closed:
                out.append(" ".join(p.strip() for p in buf))
                i = j + 1
                continue
            out.extend(buf)
            i = j
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _format_markdown_to_html(markdown_text: str) -> str:
    """Render markdown to HTML for the preview server using the `markdown` lib.

    Uses the same library as the PDF/HTML export pipeline so the preview matches
    real markdown semantics: images, tables, fenced code, blockquotes, raw HTML
    passthrough (`md_in_html`), and nested inline markup all render correctly.
    `codehilite` is intentionally omitted to avoid pulling `pygments`.

    Markdown inside raw HTML blocks (e.g. `<div align="center">`) is only
    processed by `md_in_html` when the block carries a `markdown="1"` attribute.
    Generated docs from older templates lack it, which would otherwise expose the
    block's content as literal markdown. Inject it here so both old and new docs
    render correctly without requiring regeneration. A light pass also turns
    run-on bullet lists into proper list items (see `_normalize_inline_lists`).
    """
    import markdown as md_lib

    text = _normalize_inline_lists(markdown_text)
    text = _collapse_table_cells(text)
    text = re.sub(
        r"<div([^>]*)>",
        lambda m: m.group(0) if "markdown=" in m.group(1) else f'<div{m.group(1)} markdown="1">',
        text,
    )

    return md_lib.markdown(
        text,
        extensions=["extra", "md_in_html", "toc"],
    )


def _list_markdown_pages(docs_dir: Path) -> list[str]:
    entries: list[str] = []
    for path in sorted(docs_dir.rglob("*.md")):
        if path.name == "README.md":
            continue
        entries.append(path.relative_to(docs_dir).as_posix())
    if not entries:
        entries = ["index.md"]
    return entries


def _ordered_markdown_pages(docs_dir: Path) -> list[str]:
    entries = _list_markdown_pages(docs_dir)
    preferred = ["index.md", "installation.md", "quickstart.md", "usage.md", "guides.md", "api-reference.md", "changelog.md"]
    ranking = {entry: index for index, entry in enumerate(preferred)}
    return sorted(entries, key=lambda entry: (ranking.get(entry, len(preferred)), entry))


def _label_for_entry(entry: str) -> str:
    if entry == "index.md":
        return "Home"
    name = Path(entry).stem.replace("-", " ")
    if name == "api reference":
        return "API Reference"
    if name == "changelog":
        return "Changelog"
    if name == "quickstart":
        return "Quickstart"
    if name == "installation":
        return "Installation"
    if name == "usage":
        return "Usage"
    if name == "guides":
        return "Guides & Tutorials"
    return name.title()


def _route_for_entry(entry: str) -> str:
    if entry == "index.md":
        return "/"
    return "/" + Path(entry).with_suffix("").as_posix()


def _strip_leading_title(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    if lines and lines[0].lstrip().startswith("# "):
        return "\n".join(lines[1:]).strip()
    return markdown_text.strip()


def _build_page_shell(title: str, body: str, docs_dir: Path, active_path: str | None = None) -> str:
    entries = _ordered_markdown_pages(docs_dir)
    nav_items = []
    active_route = "/"
    if active_path:
        active_route = "/" if active_path == "index.md" else "/" + Path(active_path).with_suffix("").as_posix()

    for entry in entries:
        active_class = " active" if _route_for_entry(entry) == active_route else ""
        label = _label_for_entry(entry)
        nav_items.append(f"<li class='nav-item{active_class}'><a href='{_route_for_entry(entry)}'>{label}</a></li>")
    nav_markup = "".join(nav_items)

    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{_escape_html(title)}</title>
  <style>
    :root {{ color-scheme: light; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: 'Inter', 'Segoe UI', Roboto, Arial, sans-serif; background: #f8fafc; color: #0f172a; }}
    .app-shell {{ display: grid; grid-template-columns: 280px 1fr; min-height: 100vh; }}
    .app-shell.sidebar-collapsed {{ grid-template-columns: 0 1fr; }}
    .sidebar {{ background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); color: #f8fafc; padding: 2rem 1.25rem; transition: transform 0.2s ease, width 0.2s ease; position: sticky; top: 0; align-self: start; height: 100vh; overflow-y: auto; }}
    .app-shell.sidebar-collapsed .sidebar {{ transform: translateX(-100%); width: 0; padding: 2rem 0; }}
    .sidebar h2 {{ font-size: 1.05rem; margin: 0 0 0.5rem; }}
    .sidebar p {{ color: #cbd5e1; font-size: 0.95rem; line-height: 1.5; }}
    .sidebar ul {{ list-style: none; padding: 0; margin: 1rem 0 0; display: flex; flex-direction: column; gap: 0.4rem; }}
    .sidebar a {{ color: #e2e8f0; text-decoration: none; padding: 0.55rem 0.7rem; border-radius: 8px; display: block; }}
    .sidebar a:hover {{ background: rgba(255,255,255,0.12); }}
    .sidebar .nav-item.active a {{ background: rgba(56, 189, 248, 0.2); color: #7dd3fc; }}
    .main-panel {{ display: flex; flex-direction: column; position: relative; }}
    .topbar {{ background: white; border-bottom: 1px solid #e2e8f0; padding: 1rem 1.5rem; display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; position: sticky; top: 0; z-index: 5; }}
    .topbar .title {{ font-weight: 700; font-size: 1.05rem; }}
    .topbar .meta {{ color: #64748b; font-size: 0.92rem; }}
    .topbar-actions {{ display: flex; gap: 0.6rem; align-items: center; }}
    .icon-button {{ border: 1px solid #e2e8f0; background: white; color: #0f172a; width: 2.4rem; height: 2.4rem; border-radius: 999px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; font-size: 1rem; text-decoration: none; }}
    .icon-button:hover {{ background: #f8fafc; }}
    .content {{ padding: 2rem 2.5rem; max-width: 920px; width: 100%; }}
    .card {{ background: white; border: 1px solid #e2e8f0; border-radius: 16px; padding: 2rem; box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06); }}
    h1 {{ font-size: 2rem; margin-top: 0; }}
    h2 {{ font-size: 1.35rem; margin-top: 1.5rem; }}
    h3 {{ font-size: 1.1rem; margin-top: 1.25rem; }}
    h4 {{ font-size: 1rem; margin-top: 1rem; }}
    p {{ line-height: 1.75; color: #334155; }}
    ul {{ padding-left: 1.2rem; color: #334155; }}
    li {{ margin-bottom: 0.45rem; }}
    a {{ color: #2563eb; }}
    code {{ background: #e2e8f0; padding: 0.15rem 0.35rem; border-radius: 5px; font-family: 'JetBrains Mono', Consolas, monospace; }}
    pre {{ background: #0f172a; color: #e2e8f0; padding: 1rem; border-radius: 12px; overflow-x: auto; }}
    pre code {{ background: transparent; padding: 0; color: inherit; font-family: 'JetBrains Mono', Consolas, monospace; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 0.7rem 0.85rem; text-align: left; }}
    th {{ background: #f1f5f9; }}
    .back-to-top {{ position: fixed; right: 1.25rem; bottom: 1.25rem; border: none; background: #2563eb; color: white; width: 2.8rem; height: 2.8rem; border-radius: 999px; cursor: pointer; box-shadow: 0 10px 24px rgba(37, 99, 235, 0.3); display: none; align-items: center; justify-content: center; font-size: 1.05rem; }}
    .back-to-top.show {{ display: inline-flex; }}
    @media (max-width: 900px) {{
      .app-shell {{ grid-template-columns: 1fr; }}
      .app-shell.sidebar-collapsed {{ grid-template-columns: 1fr; }}
      .sidebar {{ border-bottom: 1px solid rgba(255,255,255,0.16); }}
      .app-shell.sidebar-collapsed .sidebar {{ transform: none; width: auto; padding: 2rem 1.25rem; }}
      .content {{ padding: 1rem; }}
    }}
  </style>
</head>
<body>
  <div class=\"app-shell\" id=\"app-shell\">
    <aside class=\"sidebar\">
      <h2>Documentation</h2>
      <p>Browse generated guides and reference pages.</p>
      <ul>{nav_markup}</ul>
    </aside>
    <div class=\"main-panel\">
      <header class="topbar">
        <div class="topbar-actions">
          <button class="icon-button" id="sidebar-toggle" aria-label="Toggle sidebar" type="button">☰</button>
          <a class="icon-button" href="/" aria-label="Home" title="Home">⌂</a>
        </div>
      </header>
      <main class=\"content\">
        <section class=\"card\">{body}</section>
      </main>
    </div>
  </div>
  <button class=\"back-to-top\" id=\"back-to-top\" aria-label=\"Back to top\" type=\"button\">↑</button>
  <script>
    const shell = document.getElementById('app-shell');
    const toggleButton = document.getElementById('sidebar-toggle');
    const backToTopButton = document.getElementById('back-to-top');
    const toggleSidebar = () => {{
      shell.classList.toggle('sidebar-collapsed');
      const collapsed = shell.classList.contains('sidebar-collapsed');
      toggleButton.textContent = collapsed ? '☰' : '✕';
      toggleButton.setAttribute('aria-label', collapsed ? 'Show sidebar' : 'Hide sidebar');
    }};
    toggleButton.addEventListener('click', toggleSidebar);
    window.addEventListener('scroll', () => {{
      backToTopButton.classList.toggle('show', window.scrollY > 240);
    }});
    backToTopButton.addEventListener('click', () => window.scrollTo({{ top: 0, behavior: 'smooth' }}));
  </script>
</body>
</html>
"""


def build_docs_landing_page(docs_dir: Path) -> str:
    """Build a simple HTML landing page for the docs preview server."""
    entries = _list_markdown_pages(docs_dir)

    page_title = docs_dir.name.replace("-", " ").title() or "Documentation"
    for candidate in [docs_dir / "index.md", *[docs_dir / entry for entry in entries]]:
        if candidate.exists():
            try:
                content = candidate.read_text(encoding="utf-8")
            except Exception:
                continue
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("# "):
                    page_title = line[2:].strip()
                    break
            break

    content = ""
    index_path = docs_dir / "index.md"
    if index_path.exists():
        content = _strip_leading_title(index_path.read_text(encoding="utf-8"))
    intro = _format_markdown_to_html(content) if content else "<p>Welcome to your generated documentation preview.</p>"
    body = intro
    return _build_page_shell(page_title, body, docs_dir, None)


def build_markdown_page(docs_dir: Path, relative_path: str) -> str:
    """Render a markdown file as a simple HTML page for the preview server."""
    markdown_path = docs_dir / relative_path
    if not markdown_path.exists():
        return _build_page_shell("Not found", "<h1>Not found</h1>", docs_dir)

    content = markdown_path.read_text(encoding="utf-8")
    title = markdown_path.stem.replace("-", " ").title()
    for line in content.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    body = _format_markdown_to_html(content)
    return _build_page_shell(title, body, docs_dir, relative_path)
