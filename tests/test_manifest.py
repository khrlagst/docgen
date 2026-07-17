import json
from pathlib import Path

import pytest

from docgen.context.manifest import detect_manifest


def test_no_manifest_returns_none(tmp_path: Path):
    assert detect_manifest(tmp_path) is None


def test_package_json_node_and_react(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps({
            "name": "myapp",
            "engines": {"node": ">=18"},
            "dependencies": {"react": "^18", "next": "13"},
            "devDependencies": {"typescript": "^5"},
        }),
        encoding="utf-8",
    )
    stack = detect_manifest(tmp_path)
    # TypeScript is present in devDependencies, so the language is TypeScript
    assert stack["language"] == "TypeScript"
    assert stack["manifest"] == "package.json"
    assert stack["versions"]["node"] == ">=18"
    assert "React" in stack["frameworks"]
    assert "Next.js" in stack["frameworks"]


def test_pyproject_requires_python_and_frameworks(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "mypkg"
requires-python = ">=3.11"
dependencies = ["fastapi", "pydantic"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
""",
        encoding="utf-8",
    )
    stack = detect_manifest(tmp_path)
    assert stack["language"] == "Python"
    assert stack["versions"]["requires-python"] == ">=3.11"
    assert "FastAPI" in stack["frameworks"]
    assert "Pydantic" in stack["frameworks"]


def test_cargo_edition_and_rust_version(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text(
        """
[package]
name = "crate"
version = "0.1.0"
edition = "2021"
rust-version = "1.74"
""",
        encoding="utf-8",
    )
    stack = detect_manifest(tmp_path)
    assert stack["language"] == "Rust"
    assert stack["versions"]["edition"] == "2021"
    assert stack["versions"]["rust-version"] == "1.74"


def test_gomod_go_version(tmp_path: Path):
    (tmp_path / "go.mod").write_text(
        "module example.com/proj\n\ngo 1.22\n",
        encoding="utf-8",
    )
    stack = detect_manifest(tmp_path)
    assert stack["language"] == "Go"
    assert stack["versions"]["go"] == "1.22"


def test_detects_manifest_in_parent_dir(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "root", "dependencies": {"vue": "^3"}}),
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    stack = detect_manifest(src)
    assert stack is not None
    assert stack["language"] == "JavaScript"
    assert "Vue" in stack["frameworks"]
