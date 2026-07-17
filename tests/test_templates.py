from jinja2 import Environment
from docgen.templates.loader import create_template_env


def test_template_env_creates_loader():
    env = create_template_env(template_name="wiki")
    assert isinstance(env, Environment)


def test_index_template_renders():
    env = create_template_env(template_name="wiki")
    template = env.get_template("index.md.j2")
    output = template.render(
        project_name="MyApp",
        version="1.0.0",
        description="An app",
        language="Python",
        generation_date="2026-01-01",
        sections={
            "overview": "App overview",
            "features": "- fast\n- reliable",
        },
        toc=[
            {"title": "Installation", "file": "installation.md", "subtitle": "Setup"},
            {"title": "Usage", "file": "usage.md", "subtitle": "Guide"},
        ],
        source_modules={},
    )
    assert "# MyApp" in output
    assert "App overview" in output
    assert "Installation" in output


def test_installation_template_renders():
    env = create_template_env(template_name="wiki")
    template = env.get_template("installation.md.j2")
    output = template.render(
        project_name="MyApp",
        version="1.0.0",
        description="An app",
        language="Python",
        generation_date="2026-01-01",
        sections={"installation": "pip install myapp"},
        toc=[],
        source_modules={},
    )
    assert "Installation" in output
    assert "pip install myapp" in output


def test_api_reference_template_renders():
    env = create_template_env(template_name="wiki")
    template = env.get_template("api-reference.md.j2")
    output = template.render(
        project_name="MyApp",
        version="1.0.0",
        description="An app",
        language="Python",
        generation_date="2026-01-01",
        sections={"api_reference": "## Functions\n\n`foo()` does X."},
        toc=[],
        source_modules={
            "core.py": {
                "module_docstring": "Core module",
                "functions": [
                    {"name": "foo", "args": ["x"], "docstring": "Does X", "returns": None, "decorators": []}
                ],
                "classes": [],
            }
        },
    )
    assert "API Reference" in output
    assert "core.py" in output
    assert "foo" in output


def test_api_reference_collapses_multiline_docstrings():
    env = create_template_env(template_name="wiki")
    template = env.get_template("api-reference.md.j2")
    output = template.render(
        project_name="MyApp",
        version="1.0.0",
        description="An app",
        language="Python",
        generation_date="2026-01-01",
        sections={"api_reference": "## Functions\n\n`foo()` does X."},
        toc=[],
        source_modules={
            "core.py": {
                "module_docstring": "Core\nmodule doc",
                "functions": [
                    {"name": "foo", "args": ["x"], "docstring": "Does X\nand spans lines", "returns": None, "decorators": []}
                ],
                "classes": [
                    {"name": "Bar", "docstring": "A class\nwith detail"}
                ],
            }
        },
    )
    # Multi-line docstrings must be collapsed so table cells stay single-line.
    assert "Does X and spans lines" in output
    assert "Does X\nand spans lines" not in output
    assert "A class with detail" in output
    assert "Core module doc" in output
    # No broken table rows (stray leading pipe from a spilled row).
    assert "\n| |\n" not in output


def test_quickstart_template_renders():
    env = create_template_env(template_name="wiki")
    template = env.get_template("quickstart.md.j2")
    output = template.render(
        project_name="MyApp",
        version="1.0.0",
        description="An app",
        language="Python",
        generation_date="2026-01-01",
        sections={"quickstart": "Run `myapp start`"},
        toc=[],
        source_modules={},
    )
    assert "Quick Start" in output
    assert "Run `myapp start`" in output


def test_changelog_template_renders():
    env = create_template_env(template_name="wiki")
    template = env.get_template("changelog.md.j2")
    output = template.render(
        project_name="MyApp",
        version="1.0.0",
        description="An app",
        language="Python",
        generation_date="2026-01-01",
        sections={"changelog": "## 1.0.0\n\nInitial release"},
        toc=[],
        source_modules={},
    )
    assert "Changelog" in output
    assert "Initial release" in output


def test_usage_template_renders():
    env = create_template_env(template_name="wiki")
    template = env.get_template("usage.md.j2")
    output = template.render(
        project_name="MyApp",
        version="1.0.0",
        description="An app",
        language="Python",
        generation_date="2026-01-01",
        sections={
            "usage": "Detailed steps here",
        },
        toc=[],
        source_modules={},
    )
    assert "Usage" in output
    assert "Detailed steps" in output
    assert "Quick Start" not in output
