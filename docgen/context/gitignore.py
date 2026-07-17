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


def find_repo_root(start: Path) -> Path:
    """Locate the git repository root containing ``start``.

    Uses GitPython when available (handles worktrees and parent-directory
    discovery), and falls back to walking upward for a ``.git`` directory so the
    resolver still works outside a git checkout or without the dependency.
    """
    start = Path(start).resolve()
    try:
        from git import Repo

        repo = Repo(str(start), search_parent_directories=True)
        return Path(repo.working_dir).resolve()
    except Exception:
        pass

    current = start if start.is_dir() else start.parent
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent.resolve()
        # Also stop at the highest directory that owns a .gitignore, so a
        # project without an initialised git repo still resolves its ignores.
        if (parent / ".gitignore").exists():
            return parent.resolve()
    return start


def load_gitignore_spec(project_path: Path) -> pathspec.PathSpec:
    """Build a PathSpec from default ignores plus the project's .gitignore.

    The ``.gitignore`` is read from the git repository root containing
    ``project_path`` (discovered via :func:`find_repo_root`), so passing a
    sub-directory such as ``--source lib`` still honours the project-wide
    ignore rules instead of silently matching nothing.

    Also honours a global gitignore at ~/.gitignore_global when present, so
    user-wide ignores (editor cruft, OS files) are respected too. Git's own
    repo-local exclude file (``.git/info/exclude``) is included as well.
    """
    patterns = list(DEFAULT_IGNORES)

    global_ig = Path.home() / ".gitignore_global"
    if global_ig.exists():
        patterns.extend(global_ig.read_text(encoding="utf-8").splitlines())

    repo_root = find_repo_root(project_path)
    project_ig = repo_root / ".gitignore"
    if project_ig.exists():
        patterns.extend(project_ig.read_text(encoding="utf-8").splitlines())

    exclude = repo_root / ".git" / "info" / "exclude"
    if exclude.exists():
        patterns.extend(exclude.read_text(encoding="utf-8").splitlines())

    cleaned = [p.strip() for p in patterns if p.strip() and not p.startswith("#")]
    return pathspec.PathSpec.from_lines("gitignore", cleaned)


def is_ignored(path: Path, project_path: Path, spec: pathspec.PathSpec | None = None) -> bool:
    """True if `path` is excluded by the project's .gitignore rules.

    `path` may be absolute or relative; it is matched relative to the git
    repository root containing ``project_path`` (see :func:`find_repo_root`),
    so a sub-directory source such as ``lib`` is still tested against the
    project-wide ``.gitignore`` rather than matching nothing.
    """
    project_path = Path(project_path).resolve()
    repo_root = find_repo_root(project_path)
    try:
        rel = Path(path).resolve().relative_to(repo_root).as_posix()
    except ValueError:
        # Outside the repo: fall back to matching against project_path, then skip.
        try:
            rel = Path(path).resolve().relative_to(project_path).as_posix()
        except ValueError:
            return False
    if not rel or rel == ".":
        return False

    spec = spec or load_gitignore_spec(project_path)
    if spec.match_file(rel):
        return True
    return spec.match_file(rel.rstrip("/") + "/")
