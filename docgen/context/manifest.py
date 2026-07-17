from __future__ import annotations

import json
import re
from pathlib import Path


def detect_manifest(project_path: Path) -> dict | None:
    """Detect the project's tech stack + versions from build manifests.

    Searches `project_path` and, as a fallback, its parent so it works when the
    source dir is a subdir (e.g. `src/`). Returns None when no known manifest is
    found.

    When the manifest is only found in the *parent* directory (i.e. the project
    dir itself has no manifest), the returned dict carries ``inherited: True``.
    Callers should treat an inherited manifest's ``language`` as a weak signal —
    a project nested inside another repo (e.g. a JS app living inside a Python
    monorepo) must not be mislabeled with the parent's language. File-extension
    based detection takes precedence in that case.
    """
    project_path = Path(project_path)
    candidates = [project_path]
    if project_path.parent != project_path:
        candidates.append(project_path.parent)

    for idx, base in enumerate(candidates):
        inherited = idx > 0
        if (base / "package.json").exists():
            return _with_inherited(_parse_package_json(base / "package.json"), inherited)
        if (base / "pyproject.toml").exists():
            return _with_inherited(_parse_pyproject(base / "pyproject.toml"), inherited)
        if (base / "Cargo.toml").exists():
            return _with_inherited(_parse_cargo(base / "Cargo.toml"), inherited)
        if (base / "go.mod").exists():
            return _with_inherited(_parse_gomod(base / "go.mod"), inherited)
    return None


def _with_inherited(stack: dict, inherited: bool) -> dict:
    stack = dict(stack)
    stack["inherited"] = inherited
    return stack


def _parse_package_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"language": "JavaScript", "manifest": "package.json"}

    engines = data.get("engines", {})
    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    frameworks = _detect_js_frameworks(deps)

    stack: dict = {
        "language": "TypeScript" if "typescript" in deps else "JavaScript",
        "manifest": "package.json",
        "versions": {},
        "frameworks": frameworks,
    }
    if engines.get("node"):
        stack["versions"]["node"] = engines["node"]
    if data.get("name"):
        stack["name"] = data["name"]
    return stack


def _detect_js_frameworks(deps: dict) -> list[str]:
    known = {
        "react": "React",
        "react-dom": "React",
        "vue": "Vue",
        "next": "Next.js",
        "nextjs": "Next.js",
        "@angular/core": "Angular",
        "svelte": "Svelte",
        "@nestjs/core": "NestJS",
        "express": "Express",
        "fastify": "Fastify",
        "vite": "Vite",
        "tailwindcss": "Tailwind CSS",
    }
    found = []
    for dep in deps:
        label = known.get(dep)
        if label and label not in found:
            found.append(label)
    return found


def _parse_pyproject(path: Path) -> dict:
    try:
        import tomllib

        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (Exception):
        return {"language": "Python", "manifest": "pyproject.toml"}

    versions: dict = {}
    proj = data.get("project", {})
    rp = proj.get("requires-python")
    if rp:
        versions["requires-python"] = rp

    build_system = data.get("build-system", {})
    requires = build_system.get("requires", [])
    if requires:
        versions["build-backend"] = build_system.get("build-backend", "setuptools")

    deps = proj.get("dependencies", [])
    frameworks = _detect_python_frameworks(deps, requires)

    stack = {
        "language": "Python",
        "manifest": "pyproject.toml",
        "versions": versions,
        "frameworks": frameworks,
    }
    if proj.get("name"):
        stack["name"] = proj["name"]
    return stack


def _detect_python_frameworks(deps: list[str], requires: list[str]) -> list[str]:
    known = {
        "fastapi": "FastAPI",
        "flask": "Flask",
        "django": "Django",
        "pydantic": "Pydantic",
        "sqlalchemy": "SQLAlchemy",
        "starlette": "Starlette",
        "click": "Click",
        "typer": "Typer",
    }
    found = []
    for dep in [*deps, *requires]:
        name = re.split(r"[<>=!~ ]", dep.strip(), 1)[0].strip()
        label = known.get(name)
        if label and label not in found:
            found.append(label)
    return found


def _parse_cargo(path: Path) -> dict:
    text = ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"language": "Rust", "manifest": "Cargo.toml"}

    versions: dict = {}
    m = re.search(r'^\s*edition\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if m:
        versions["edition"] = m.group(1)
    m = re.search(r'^\s*rust-version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if m:
        versions["rust-version"] = m.group(1)

    return {
        "language": "Rust",
        "manifest": "Cargo.toml",
        "versions": versions,
        "frameworks": [],
    }


def _parse_gomod(path: Path) -> dict:
    text = ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"language": "Go", "manifest": "go.mod"}

    versions: dict = {}
    m = re.search(r'^\s*go\s+(\d+\.\d+(?:\.\d+)?)', text, re.MULTILINE)
    if m:
        versions["go"] = m.group(1)

    return {
        "language": "Go",
        "manifest": "go.mod",
        "versions": versions,
        "frameworks": [],
    }
