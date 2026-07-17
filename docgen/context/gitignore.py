from __future__ import annotations

from pathlib import Path

import pathspec


DEFAULT_IGNORES = [
    ".git/",
    "__pycache__/",
    "*.pyc",
    "node_modules/",
    "dist/",
    "build/",
    ".docgen/",
    ".venv/",
    "venv/",
]


def load_gitignore_spec(project_path: Path) -> pathspec.PathSpec:
    """Build a PathSpec from default ignores plus the project's .gitignore.

    Also honours a global gitignore at ~/.gitignore_global when present, so
    user-wide ignores (editor cruft, OS files) are respected too.
    """
    patterns = list(DEFAULT_IGNORES)

    global_ig = Path.home() / ".gitignore_global"
    if global_ig.exists():
        patterns.extend(global_ig.read_text(encoding="utf-8").splitlines())

    project_ig = Path(project_path) / ".gitignore"
    if project_ig.exists():
        patterns.extend(project_ig.read_text(encoding="utf-8").splitlines())

    cleaned = [p.strip() for p in patterns if p.strip() and not p.startswith("#")]
    return pathspec.PathSpec.from_lines("gitignore", cleaned)


def is_ignored(path: Path, project_path: Path, spec: pathspec.PathSpec | None = None) -> bool:
    """True if `path` is excluded by the project's .gitignore rules.

    `path` may be absolute or relative; it is matched against the project root.
    """
    try:
        rel = Path(path).resolve().relative_to(Path(project_path).resolve()).as_posix()
    except ValueError:
        return False
    if not rel or rel == ".":
        return False

    spec = spec or load_gitignore_spec(project_path)
    if spec.match_file(rel):
        return True
    return spec.match_file(rel.rstrip("/") + "/")
