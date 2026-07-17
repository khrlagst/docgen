from docgen.output.markdown import build_docs_landing_page, build_markdown_page


def test_build_docs_landing_page_lists_markdown_pages(tmp_path):
    (tmp_path / "index.md").write_text("# Example Docs\n\nWelcome to the docs.\n", encoding="utf-8")
    (tmp_path / "guide.md").write_text("## Guide\n\nUse the guide.\n", encoding="utf-8")

    html = build_docs_landing_page(tmp_path)

    assert "<!DOCTYPE html>" in html
    assert "Example Docs" in html
    assert "Guide" in html
    assert "guide.md" not in html


def test_build_markdown_page_renders_html(tmp_path):
    (tmp_path / "guide.md").write_text("# Guide\n\nUse the guide.\n", encoding="utf-8")

    html = build_markdown_page(tmp_path, "guide.md")

    assert "<!DOCTYPE html>" in html
    assert "<h1" in html
    assert ">Guide</h1>" in html
    assert "Use the guide." in html
    assert "sidebar" in html


def test_build_markdown_page_renders_tables_and_code_blocks(tmp_path):
    (tmp_path / "guide.md").write_text(
        "# Guide\n\n| Name | Value |\n| --- | --- |\n| One | Two |\n\n```python\nprint('hello')\n```\n",
        encoding="utf-8",
    )

    html = build_markdown_page(tmp_path, "guide.md")

    assert "<table" in html
    assert "<th>Name</th>" in html
    assert "<pre><code" in html
    assert "print('hello')" in html


def test_renderer_handles_blockquote_hr_html_and_lists(tmp_path):
    (tmp_path / "page.md").write_text(
        "# Page\n\n> a blockquote\n\n---\n\n"
        "<div align=\"center\">\n\ncentered\n\n</div>\n\n"
        "- [**Install**](installation.md) — Setup\n",
        encoding="utf-8",
    )

    html = build_markdown_page(tmp_path, "page.md")

    assert "<blockquote>" in html
    assert "<hr" in html
    assert "<div" in html
    assert "&lt;div" not in html
    assert "<ul>" in html
    assert "<a href=\"installation.md\">" in html


def test_renderer_renders_image_badges(tmp_path):
    (tmp_path / "page.md").write_text(
        "[![Version](https://img.shields.io/badge/version-1.0-blue.svg)](https://github.com/x)\n",
        encoding="utf-8",
    )

    html = build_markdown_page(tmp_path, "page.md")

    assert "<img" in html
    assert "![Version" not in html


def test_renderer_processes_div_without_markdown_attribute(tmp_path):
    # Old templates emit `<div align="center">` without `markdown="1"`; the
    # renderer must still process its inner markdown instead of exposing it raw.
    (tmp_path / "page.md").write_text(
        "<div align=\"center\">\n\n# Title\n\n> a quote\n\n"
        "[![Version](https://img.shields.io/badge/version-1.0-blue.svg)](https://github.com/x)\n\n</div>\n",
        encoding="utf-8",
    )

    html = build_markdown_page(tmp_path, "page.md")

    assert "<h1" in html
    assert "<blockquote>" in html
    assert "<img" in html
    assert "![Version" not in html


def test_landing_page_omits_redundant_pages_list(tmp_path):
    (tmp_path / "index.md").write_text("# Home\n\nWelcome.\n", encoding="utf-8")
    (tmp_path / "installation.md").write_text("## Installation\n", encoding="utf-8")

    html = build_docs_landing_page(tmp_path)

    assert "<!DOCTYPE html>" in html
    assert "<h2>Pages</h2>" not in html
    assert "Welcome." in html


def test_docs_navigation_uses_readable_labels_and_h4_headings(tmp_path):
    (tmp_path / "index.md").write_text("# Home\n\nWelcome.\n", encoding="utf-8")
    (tmp_path / "api-reference.md").write_text("## API Reference\n", encoding="utf-8")
    (tmp_path / "installation.md").write_text("#### Installation\n", encoding="utf-8")

    html = build_markdown_page(tmp_path, "installation.md")

    assert ">Installation</h4>" in html
    assert "Home" in html
    assert "API Reference" in html
    assert "installation.md" not in html
    assert "api-reference.md" not in html


def test_sidebar_renames_guides_to_guides_and_tutorials(tmp_path):
    (tmp_path / "index.md").write_text("# Home\n", encoding="utf-8")
    (tmp_path / "guides.md").write_text("# Guides\n", encoding="utf-8")

    html = build_markdown_page(tmp_path, "guides.md")

    assert "Guides & Tutorials" in html
    assert "Guides</a>" not in html


def test_topbar_omits_markdown_preview_and_page_title(tmp_path):
    (tmp_path / "guide.md").write_text("# Changelog\n\nbody\n", encoding="utf-8")

    html = build_markdown_page(tmp_path, "guide.md")

    assert "Markdown preview" not in html
    assert 'class="title"' not in html


def test_renderer_turns_inline_list_runs_into_bullets(tmp_path):
    (tmp_path / "page.md").write_text(
        "# Page\n\n"
        "The core architecture consists of: - Context Collection: scans files "
        "- LLM Integration: calls AI - Output Formats: renders docs\n",
        encoding="utf-8",
    )

    html = build_markdown_page(tmp_path, "page.md")

    assert "<ul>" in html
    assert "Context Collection: scans files" in html
    assert "LLM Integration: calls AI" in html
    assert "Output Formats: renders docs" in html


def test_renderer_collapses_multiline_table_cells(tmp_path):
    (tmp_path / "page.md").write_text(
        "# Page\n\n"
        "| Function | Description |\n"
        "|----------|-------------|\n"
        "| `foo` | Does X.\n\n"
        "More detail about foo that spilled onto another line. |\n",
        encoding="utf-8",
    )

    html = build_markdown_page(tmp_path, "page.md")

    assert "<table" in html
    assert "More detail about foo that spilled onto another line." in html
    # The spilled row must not leak as a raw markdown table line.
    assert "| |" not in html
    assert "Does X." in html

