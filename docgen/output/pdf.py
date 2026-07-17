from pathlib import Path

STYLESHEET_PATH = Path(__file__).parent / "docgen.css"
PAGE_ORDER = ["index", "installation", "quickstart", "usage", "api-reference", "changelog"]


def markdown_to_pdf(
    md_dir: Path,
    output_pdf: Path,
    engine: str = "weasyprint",
    stylesheet: Path | None = None,
):
    if engine == "weasyprint":
        _weasyprint_export(md_dir, output_pdf, stylesheet or STYLESHEET_PATH)
    elif engine == "pandoc":
        _pandoc_export(md_dir, output_pdf)
    else:
        raise ValueError(f"Unknown PDF engine: {engine}. Choose 'weasyprint' or 'pandoc'.")


def _get_pages_in_order(md_dir: Path) -> list[Path]:
    files = {f.stem: f for f in md_dir.rglob("*.md")}
    pages = []
    for name in PAGE_ORDER:
        if name in files:
            pages.append(files[name])
    for f in sorted(md_dir.rglob("*.md")):
        if f.stem not in PAGE_ORDER:
            pages.append(f)
    return pages


def markdown_to_html(md_dir: Path, stylesheet: Path | None = None) -> str:
    """Combine all markdown files into a single HTML string."""
    import markdown as md_lib

    pages = _get_pages_in_order(md_dir)
    all_md = [p.read_text(encoding="utf-8") for p in pages]
    combined_md = "\n\n<hr style='page-break-before: always;'>\n\n".join(all_md)

    html = md_lib.markdown(
        combined_md,
        extensions=["extra", "codehilite", "toc", "md_in_html"],
    )

    css = ""
    if stylesheet and stylesheet.exists():
        css = stylesheet.read_text(encoding="utf-8")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
{css}
</style>
</head>
<body>
{html}
</body>
</html>"""


def _block_remote_fetcher(url: str, *args, **kwargs):
    """URL fetcher that refuses any network access during PDF rendering.

    Generated docs may contain remote image/CSS references; fetching them would
    leak data and make builds non-hermetic. We only allow local ``file://`` and
    ``data:`` URLs (the latter is how inlined stylesheets/CSS are passed).
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme in ("", "file", "data"):
        from weasyprint.urls import default_url_fetcher

        return default_url_fetcher(url, *args, **kwargs)
    raise PermissionError(f"Blocked remote resource during PDF export: {url}")


def _weasyprint_export(
    md_dir: Path,
    output_pdf: Path,
    stylesheet: Path | None = None,
):
    try:
        from weasyprint import HTML
    except ImportError:
        raise ImportError(
            "Missing optional dependencies for PDF export. "
            "Run: pip install docgen[pdf]"
        )

    pages = _get_pages_in_order(md_dir)
    all_md = [p.read_text(encoding="utf-8") for p in pages]
    combined_md = "\n\n<div style='page-break-before: always;'></div>\n\n".join(all_md)

    html = md_lib.markdown(
        combined_md,
        extensions=["extra", "codehilite", "toc", "md_in_html"],
    )

    css = ""
    if stylesheet and stylesheet.exists():
        css = stylesheet.read_text(encoding="utf-8")

    full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
{css}
</style>
</head>
<body>
{html}
</body>
</html>"""

    # ``url_fetcher`` blocks remote fetches so docs are rendered hermetically.
    HTML(string=full_html, url_fetcher=_block_remote_fetcher).write_pdf(
        str(output_pdf)
    )


def _pandoc_export(md_dir: Path, output_pdf: Path):
    import subprocess
    import shutil

    if not shutil.which("pandoc"):
        raise FileNotFoundError(
            "pandoc is not installed. Install it from https://pandoc.org/"
        )

    pages = _get_pages_in_order(md_dir)
    temp = md_dir / ".docgen_temp.md"
    combined = "\n\n\\newpage\n\n".join(
        p.read_text(encoding="utf-8") for p in pages
    )
    temp.write_text(combined, encoding="utf-8")
    try:
        subprocess.run(
            [
                "pandoc",
                str(temp),
                "-o", str(output_pdf),
                "--from=gfm",
                "--toc",
                "-V", "geometry:margin=1in",
            ],
            check=True,
        )
    finally:
        if temp.exists():
            temp.unlink()
