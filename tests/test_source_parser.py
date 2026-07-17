import pytest
from docgen.context.source import SourceParser, build_project_tree, summarize_workflows


@pytest.fixture
def sample_source():
    return '''
def greet(name: str, times: int = 1) -> str:
    """Say hello multiple times."""
    return f"Hello {name} " * times


class Calculator:
    """A simple calculator."""

    def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    def subtract(self, a: int, b: int) -> int:
        """Subtract b from a."""
        return a - b


async def fetch_data(url: str) -> dict:
    """Fetch data from a URL."""
    return {"data": "mock"}
'''


def test_parses_functions(sample_source):
    parser = SourceParser(sample_source)
    result = parser.parse()
    names = [f["name"] for f in result["functions"]]
    assert "greet" in names
    assert "fetch_data" in names


def test_parses_function_args(sample_source):
    parser = SourceParser(sample_source)
    result = parser.parse()
    greet = next(f for f in result["functions"] if f["name"] == "greet")
    assert greet["args"] == ["name", "times"]


def test_parses_function_docstrings(sample_source):
    parser = SourceParser(sample_source)
    result = parser.parse()
    greet = next(f for f in result["functions"] if f["name"] == "greet")
    assert greet["docstring"] == "Say hello multiple times."


def test_parses_function_returns(sample_source):
    parser = SourceParser(sample_source)
    result = parser.parse()
    greet = next(f for f in result["functions"] if f["name"] == "greet")
    assert greet["returns"] == "str"


def test_parses_classes(sample_source):
    parser = SourceParser(sample_source)
    result = parser.parse()
    names = [c["name"] for c in result["classes"]]
    assert "Calculator" in names


def test_parses_class_methods(sample_source):
    parser = SourceParser(sample_source)
    result = parser.parse()
    calc = next(c for c in result["classes"] if c["name"] == "Calculator")
    method_names = [m["name"] for m in calc["methods"]]
    assert "add" in method_names
    assert "subtract" in method_names


def test_parses_class_docstrings(sample_source):
    parser = SourceParser(sample_source)
    result = parser.parse()
    calc = next(c for c in result["classes"] if c["name"] == "Calculator")
    assert calc["docstring"] == "A simple calculator."


def test_module_docstring():
    source = '"""Module-level docs."""\n\nx = 1'
    parser = SourceParser(source)
    result = parser.parse()
    assert result["module_docstring"] == "Module-level docs."


def test_empty_source():
    parser = SourceParser("")
    result = parser.parse()
    assert result["functions"] == []
    assert result["classes"] == []
    assert result["module_docstring"] is None


def test_async_function_parsed(sample_source):
    parser = SourceParser(sample_source)
    result = parser.parse()
    fetch = next(f for f in result["functions"] if f["name"] == "fetch_data")
    assert fetch["args"] == ["url"]


def test_project_tree_excludes_generated_docs(tmp_path):
    (tmp_path / "mod.py").write_text("def f(): pass\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text("# Generated\n")
    tree = build_project_tree(tmp_path)
    assert "docs" not in tree
    assert "mod.py" in tree


def test_summarize_workflows_excludes_generated_docs(tmp_path):
    (tmp_path / "app.py").write_text("def main(): pass\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text("# Generated\n")
    summary = summarize_workflows(tmp_path)
    assert "docs" not in summary
    assert "app.py" in summary
