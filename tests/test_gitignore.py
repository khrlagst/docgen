from pathlib import Path

import pytest

from docgen.context.gitignore import is_ignored, load_gitignore_spec
from docgen.context.source import parse_project, read_source_files, build_project_tree


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".gitignore").write_text(
        "node_modules/\ndist/\nsecret.txt\n", encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "node_modules" / "lib").mkdir(parents=True)
    (tmp_path / "node_modules" / "lib" / "x.js").write_text("// lib\n", encoding="utf-8")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "bundle.js").write_text("// built\n", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("nope\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "app.cpython-312.pyc").write_text("x", encoding="utf-8")
    return tmp_path


def test_load_gitignore_spec_reads_project(project: Path):
    spec = load_gitignore_spec(project)
    assert spec.match_file("node_modules/lib/x.js")
    assert spec.match_file("dist/bundle.js")
    assert spec.match_file("secret.txt")
    # default ignore still applies
    assert spec.match_file("__pycache__/app.cpython-312.pyc")


def test_is_ignored_true_for_ignored_paths(project: Path):
    assert is_ignored(project / "node_modules" / "lib" / "x.js", project)
    assert is_ignored(project / "dist" / "bundle.js", project)
    assert is_ignored(project / "secret.txt", project)
    assert is_ignored(project / ".docgen" / "config.toml", project)


def test_is_ignored_false_for_source(project: Path):
    assert not is_ignored(project / "src" / "app.py", project)


def test_read_source_files_skips_ignored(project: Path):
    files = read_source_files(project, token_budget=10_000_000)
    keys = [Path(p).as_posix() for p in files]
    assert "src/app.py" in keys
    assert all("node_modules" not in k.split("/") for k in keys)
    assert all("dist" not in k.split("/") for k in keys)
    assert all("__pycache__" not in k.split("/") for k in keys)


def test_build_project_tree_skips_ignored(project: Path):
    tree = build_project_tree(project)
    assert "src/app.py" in tree
    assert "node_modules" not in tree
    assert "dist" not in tree
    assert "secret.txt" not in tree


def test_token_budget_limits_read(project: Path):
    big = read_source_files(project, token_budget=10_000_000)
    small = read_source_files(project, token_budget=1)
    big_keys = {Path(p).as_posix() for p in big}
    small_keys = {Path(p).as_posix() for p in small}
    # a smaller budget never returns more files than a large one
    assert small_keys.issubset(big_keys)
    for k in big_keys | small_keys:
        parts = k.split("/")
        assert "node_modules" not in parts
        assert "dist" not in parts
        assert "__pycache__" not in parts


def test_parse_project_skips_ignored(project: Path):
    modules = parse_project(project)
    keys = [Path(p).as_posix() for p in modules]
    assert "src/app.py" in keys
    assert all("node_modules" not in k.split("/") for k in keys)


def test_gitignore_honoured_from_subdir_source(project: Path):
    """A ``--source`` sub-directory must still honour the repo-root .gitignore."""
    sub = project / "src"
    spec = load_gitignore_spec(sub)
    assert spec.match_file("node_modules/lib/x.js")
    assert spec.match_file("dist/bundle.js")
    # `secret.txt` (no slash) matches at any depth, including repo root
    assert spec.match_file("secret.txt")
    assert spec.match_file("src/secret.txt")
    # and the functions accept the subdir as the project path
    assert is_ignored(project / "node_modules" / "lib" / "x.js", sub)
    files = read_source_files(sub, token_budget=10_000_000)
    keys = [Path(p).as_posix() for p in files]
    assert "app.py" in keys
    assert all("node_modules" not in k.split("/") for k in keys)
    assert all("dist" not in k.split("/") for k in keys)
