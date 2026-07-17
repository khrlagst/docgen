"""Extract the real CLI / Python API surface of a project for prompt grounding.

When docgen documents a project, the "usage" and "quickstart" sections must describe
the *actual* commands and API — not ones the LLM invents. This module discovers the
ground truth by reading `[project.scripts]` from `pyproject.toml` and introspecting the
Typer/click app (or by `ast`-scanning the package for public symbols).

It is intentionally defensive: any failure returns an empty string so a project without
a detectable CLI simply gets no grounding section rather than crashing generation.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


def find_project_root(path) -> Path | None:
    """Walk up from ``path`` to the nearest directory containing a project manifest."""
    current = Path(path).resolve()
    candidates = [current, *current.parents]
    for candidate in candidates:
        if (candidate / "pyproject.toml").exists() or (candidate / "setup.py").exists():
            return candidate
    return None


def detect_console_scripts(root: Path) -> list[tuple[str, str]]:
    """Return ``[(script_name, "module:attr"), ...]`` from project entry points."""
    root = Path(root)
    scripts: list[tuple[str, str]] = []

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            import tomllib

            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            raw = (data.get("project", {}) or {}).get("scripts", {}) or {}
            for name, target in raw.items():
                scripts.append((name, target))
        except Exception:
            pass

    if not scripts:
        setup_py = root / "setup.py"
        if setup_py.exists():
            text = setup_py.read_text(encoding="utf-8")
            for match in re.finditer(
                r"([\w\-]+)\s*=\s*['\"]([\w\.]+:[\w\.]+)['\"]", text
            ):
                scripts.append((match.group(1), match.group(2)))

    return scripts


def _format_command(cmd, prefix: str, lines: list[str]) -> None:
    """Recursively render a click command/group into bullet lines."""
    import click

    help_text = (cmd.help or "").strip().split("\n")[0]
    opts: list[str] = []
    for param in getattr(cmd, "params", []) or []:
        for opt in getattr(param, "opts", []) or []:
            opts.append(opt)

    line = f"- `{prefix}`"
    if help_text:
        line += f" — {help_text}"
    if opts:
        line += f"  (options: {' '.join(opts)})"
    lines.append(line)

    if isinstance(cmd, click.Group):
        for sub in cmd.commands.values():
            _format_command(sub, f"{prefix} {sub.name}", lines)


def introspect_cli(target: str, script_name: str) -> str:
    """Introspect a ``module:attr`` Typer/click app into a command reference string."""
    try:
        import importlib

        import typer

        module_path, attr = target.split(":")
        module = importlib.import_module(module_path)
        obj = getattr(module, attr)
        cmd = typer.main.get_command(obj)

        lines: list[str] = []
        for sub in cmd.commands.values():
            _format_command(sub, f"{script_name} {sub.name}", lines)
        return "\n".join(lines)
    except Exception:
        return ""


def public_api_symbols(root: Path, limit: int = 40) -> list[str]:
    """List public top-level classes/functions across the package via ``ast``.

    Classes are listed before functions so the high-level public API survives the
    cap (e.g. ``GenerationEngine`` / ``ContextCollector`` are kept ahead of helpers).
    """
    root = Path(root)
    classes: list[str] = []
    functions: list[str] = []
    seen: set[str] = set()

    for py in sorted(root.rglob("*.py")):
        parts = py.parts
        if any(p.startswith(".") for p in parts):
            continue
        rel = py.relative_to(root)
        if "tests" in parts:
            continue
        if rel.name.startswith("test_") or (
            rel.name.startswith("_") and rel.name != "__init__.py"
        ):
            continue

        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except Exception:
            continue

        module_id = ".".join([*rel.with_suffix("").parts])
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                key = f"{module_id}.{node.name}"
                if key in seen:
                    continue
                seen.add(key)
                if isinstance(node, ast.ClassDef):
                    classes.append(key)
                else:
                    functions.append(key)

    classes.sort()
    functions.sort()
    return (classes + functions)[:limit]


def cli_surface_text(project_path) -> str:
    """Return a grounded CLI/API reference for ``project_path``, or ``""`` if none."""
    root = find_project_root(project_path)
    if not root:
        return ""

    scripts = detect_console_scripts(root)
    blocks: list[str] = []

    for name, target in scripts:
        cli_text = introspect_cli(target, name)
        if cli_text:
            blocks.append(f"### Commands (`{name}`)\n{cli_text}")

    api = public_api_symbols(root)
    if api:
        api_lines = "\n".join(f"- `{sym}`" for sym in api)
        blocks.append(f"### Python API (public symbols)\n{api_lines}")

    return "\n\n".join(blocks)
