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

    # Order matters: prefer the most specific manifest in the project itself.
    manifest_checks = [
        ("package.json", _parse_package_json),
        ("pyproject.toml", _parse_pyproject),
        ("Cargo.toml", _parse_cargo),
        ("go.mod", _parse_gomod),
        ("pubspec.yaml", _parse_pubspec),          # Dart / Flutter
        ("build.gradle", _parse_gradle),           # Groovy DSL (Android/JVM)
        ("build.gradle.kts", _parse_gradle),       # Kotlin DSL
        ("pom.xml", _parse_pom),                   # Maven (Java/Kotlin/Scala)
        ("composer.json", _parse_composer),        # PHP
        ("Gemfile", _parse_gemfile),               # Ruby
        ("*.csproj", _parse_csproj),               # .NET / C#
        ("Package.swift", _parse_swift),           # Swift
        ("mix.exs", _parse_mix),                   # Elixir
        ("Cargo.toml (workspace)", None),          # placeholder (handled by Cargo)
    ]

    for idx, base in enumerate(candidates):
        inherited = idx > 0
        # Exact-name manifests first.
        for filename, parser in manifest_checks:
            if parser is None or "*" in filename:
                continue
            manifest = base / filename
            if manifest.exists():
                return _with_inherited(parser(manifest), inherited)
        # Glob manifests (e.g. any *.csproj) for the project root.
        for filename, parser in manifest_checks:
            if parser is None or "*" not in filename:
                continue
            matches = list(base.glob(filename))
            if matches:
                return _with_inherited(parser(matches[0]), inherited)
    return None


def _with_inherited(stack: dict, inherited: bool) -> dict:
    stack = dict(stack)
    stack["inherited"] = inherited
    return stack


# --------------------------------------------------------------------------
# JavaScript / TypeScript
# --------------------------------------------------------------------------

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
        "nuxt": "Nuxt",
        "remix": "Remix",
        "astro": "Astro",
        "gatsby": "Gatsby",
        "electron": "Electron",
        "react-native": "React Native",
        "expo": "Expo",
    }
    found = []
    for dep in deps:
        label = known.get(dep)
        if label and label not in found:
            found.append(label)
    return found


# --------------------------------------------------------------------------
# Python
# --------------------------------------------------------------------------

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
        "streamlit": "Streamlit",
        "dash": "Dash",
        "tornado": "Tornado",
        "aiohttp": "aiohttp",
        "celery": "Celery",
        "numpy": "NumPy",
        "pandas": "pandas",
        "scipy": "SciPy",
        "torch": "PyTorch",
        "tensorflow": "TensorFlow",
    }
    found = []
    for dep in [*deps, *requires]:
        name = re.split(r"[<>=!~ ]", dep.strip(), 1)[0].strip()
        label = known.get(name)
        if label and label not in found:
            found.append(label)
    return found


# --------------------------------------------------------------------------
# Rust
# --------------------------------------------------------------------------

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

    frameworks = []
    if re.search(r'^\s*actix\s*=', text, re.MULTILINE):
        frameworks.append("Actix")
    if re.search(r'^\s*axum\s*=', text, re.MULTILINE):
        frameworks.append("Axum")
    if re.search(r'^\s*rocket\s*=', text, re.MULTILINE):
        frameworks.append("Rocket")
    if re.search(r'^\s*tonic\s*=', text, re.MULTILINE):
        frameworks.append("Tonic (gRPC)")
    if re.search(r'^\s*dioxus\s*=', text, re.MULTILINE):
        frameworks.append("Dioxus")
    if re.search(r'^\s*bevy\s*=', text, re.MULTILINE):
        frameworks.append("Bevy")

    return {
        "language": "Rust",
        "manifest": "Cargo.toml",
        "versions": versions,
        "frameworks": frameworks,
    }


# --------------------------------------------------------------------------
# Go
# --------------------------------------------------------------------------

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

    frameworks = []
    if re.search(r'\bgin-gonic/gin\b', text):
        frameworks.append("Gin")
    if re.search(r'\bgo-chi/chi\b', text):
        frameworks.append("chi")
    if re.search(r'\becho\b', text):
        frameworks.append("Echo")
    if re.search(r'\bfiber\b', text):
        frameworks.append("Fiber")

    return {
        "language": "Go",
        "manifest": "go.mod",
        "versions": versions,
        "frameworks": frameworks,
    }


# --------------------------------------------------------------------------
# Dart / Flutter
# --------------------------------------------------------------------------

def _parse_pubspec(path: Path) -> dict:
    text = ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"language": "Dart", "manifest": "pubspec.yaml"}

    versions: dict = {}
    name = None
    frameworks: list[str] = []
    sdk = None
    is_flutter = False
    in_environment = False

    for line in text.splitlines():
        m = re.match(r'\s*name:\s*(\S+)', line)
        if m:
            name = m.group(1)
        # Only the `environment:` block's `sdk:` is the Dart/Flutter SDK
        # constraint; a `flutter:` dependency line is not.
        if re.match(r'\s*environment:\s*$', line):
            in_environment = True
            continue
        if in_environment:
            if re.match(r'\s*sdk:\s*([\'"]?)([^\'"\s]+)', line):
                sdk = re.match(r'\s*sdk:\s*([\'"]?)([^\'"\s]+)', line).group(2)
                in_environment = False
            elif re.match(r'\s*\S', line) and not line.startswith((" ", "\t")):
                # Left the environment block.
                in_environment = False
        # A `flutter:` dependency (with the sdk: flutter sub-key) marks a
        # Flutter project; `flutter_*` packages are framework signals only.
        if re.match(r'\s*flutter:\s*$', line) or re.match(r'\s*sdk:\s*flutter\s*$', line):
            is_flutter = True

    # Look at dependency block for framework signals.
    deps_text = text
    if re.search(r'^\s*flutter_web', deps_text, re.MULTILINE):
        frameworks.append("Flutter Web")
    if re.search(r'^\s*flutter_riverpod|riverpod', deps_text, re.MULTILINE):
        frameworks.append("Riverpod")
    if re.search(r'^\s*get\b', deps_text, re.MULTILINE):
        frameworks.append("GetX")
    if re.search(r'^\s*bloc\b', deps_text, re.MULTILINE):
        frameworks.append("Bloc")

    if sdk:
        versions["sdk"] = sdk

    return {
        "language": "Flutter" if is_flutter else "Dart",
        "manifest": "pubspec.yaml",
        "versions": versions,
        "frameworks": frameworks,
        **({"name": name} if name else {}),
    }


# --------------------------------------------------------------------------
# JVM (Gradle)
# --------------------------------------------------------------------------

def _parse_gradle(path: Path) -> dict:
    text = ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"language": "Java", "manifest": path.name}

    language = "Java"
    if re.search(r'\bkotlin\b', text) and "org.jetbrains.kotlin" in text:
        language = "Kotlin"
    if re.search(r'\bid "org.jetbrains.kotlin|kotlin\(', text):
        language = "Kotlin"

    frameworks: list[str] = []
    if "org.springframework" in text or "spring-boot" in text:
        frameworks.append("Spring Boot")
    if "android" in text:
        frameworks.append("Android")
    if "com.android" in text:
        frameworks.append("Android")
    if "ktor" in text:
        frameworks.append("Ktor")
    if "play" in text:
        frameworks.append("Play Framework")
    if "quarkus" in text:
        frameworks.append("Quarkus")

    versions: dict = {}
    m = re.search(r'jvmTarget\s*=\s*["\']?(\d+)', text)
    if m:
        versions["jvmTarget"] = m.group(1)
    m = re.search(r'sourceCompatibility\s*=\s*JavaVersion\.VERSION_(\w+)', text)
    if m:
        versions["java"] = m.group(1)

    return {
        "language": language,
        "manifest": path.name,
        "versions": versions,
        "frameworks": frameworks,
    }


# --------------------------------------------------------------------------
# JVM (Maven)
# --------------------------------------------------------------------------

def _parse_pom(path: Path) -> dict:
    text = ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"language": "Java", "manifest": "pom.xml"}

    language = "Java"
    if "<kotlin" in text or "kotlin-maven" in text or "scala" in text:
        if "scala" in text:
            language = "Scala"
        elif "kotlin" in text:
            language = "Kotlin"

    versions: dict = {}
    m = re.search(r'<java.version>([^<]+)</java.version>', text)
    if m:
        versions["java"] = m.group(1)
    m = re.search(r'<spring-boot.version>([^<]+)</spring-boot.version>', text)
    if m:
        versions["spring-boot"] = m.group(1)

    frameworks: list[str] = []
    if "springframework" in text or "spring-boot" in text:
        frameworks.append("Spring Boot")
    if "quarkus" in text:
        frameworks.append("Quarkus")
    if "micronaut" in text:
        frameworks.append("Micronaut")
    if "play" in text:
        frameworks.append("Play Framework")
    if "scala" in text:
        frameworks.append("Scala")

    return {
        "language": language,
        "manifest": "pom.xml",
        "versions": versions,
        "frameworks": frameworks,
    }


# --------------------------------------------------------------------------
# PHP (Composer)
# --------------------------------------------------------------------------

def _parse_composer(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"language": "PHP", "manifest": "composer.json"}

    require = {**data.get("require", {}), **data.get("require-dev", {})}
    frameworks = _detect_php_frameworks(require)

    versions: dict = {}
    if require.get("php"):
        versions["php"] = require["php"]

    return {
        "language": "PHP",
        "manifest": "composer.json",
        "versions": versions,
        "frameworks": frameworks,
        **({"name": data["name"]} if data.get("name") else {}),
    }


def _detect_php_frameworks(deps: dict) -> list[str]:
    known = {
        "laravel/framework": "Laravel",
        "symfony/symfony": "Symfony",
        "phpunit/phpunit": "PHPUnit",
        "guzzlehttp/guzzle": "Guzzle",
        "cakephp/cakephp": "CakePHP",
        "codeigniter4/framework": "CodeIgniter",
        "slim/slim": "Slim",
        "yiisoft/yii2": "Yii",
        "illuminate/": "Laravel",
        "wp-coding-standards": "WordPress",
    }
    found = []
    for dep in deps:
        for key, label in known.items():
            if dep.startswith(key) and label not in found:
                found.append(label)
                break
    return found


# --------------------------------------------------------------------------
# Ruby (Bundler Gemfile)
# --------------------------------------------------------------------------

def _parse_gemfile(path: Path) -> dict:
    text = ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"language": "Ruby", "manifest": "Gemfile"}

    frameworks: list[str] = []
    if re.search(r"gem\s+['\"]rails", text):
        frameworks.append("Rails")
    if re.search(r"gem\s+['\"]sinatra", text):
        frameworks.append("Sinatra")
    if re.search(r"gem\s+['\"]hanami", text):
        frameworks.append("Hanami")
    if re.search(r"gem\s+['\"]jekyll", text):
        frameworks.append("Jekyll")
    if re.search(r"gem\s+['\"]rspec", text):
        frameworks.append("RSpec")

    versions: dict = {}
    m = re.search(r"ruby\s+['\"]([^'\"]+)", text)
    if m:
        versions["ruby"] = m.group(1)

    return {
        "language": "Ruby",
        "manifest": "Gemfile",
        "versions": versions,
        "frameworks": frameworks,
    }


# --------------------------------------------------------------------------
# .NET / C# (csproj / sln / vbproj)
# --------------------------------------------------------------------------

def _parse_csproj(path: Path) -> dict:
    text = ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"language": "C#", "manifest": path.name}

    language = "C#"
    if path.suffix.lower() == ".fsproj":
        language = "F#"
    elif path.suffix.lower() == ".vbproj":
        language = "Visual Basic"

    frameworks: list[str] = []
    if "Microsoft.NET.Sdk.Web" in text or "<Web" in text:
        frameworks.append("ASP.NET Core")
    if "Microsoft.NET.Sdk.Blazor" in text or "blazor" in text.lower():
        frameworks.append("Blazor")
    if "MAUI" in text or "Microsoft.NET.Sdk.Maui" in text:
        frameworks.append(".NET MAUI")
    if "Xamarin" in text:
        frameworks.append("Xamarin")
    if "EntityFramework" in text or "Microsoft.EntityFrameworkCore" in text:
        frameworks.append("Entity Framework")

    versions: dict = {}
    m = re.search(r"<TargetFramework>([^<]+)</TargetFramework>", text)
    if m:
        versions["target"] = m.group(1)
    m = re.search(r"<LangVersion>([^<]+)</LangVersion>", text)
    if m:
        versions["lang"] = m.group(1)

    return {
        "language": language,
        "manifest": path.name,
        "versions": versions,
        "frameworks": frameworks,
    }


# --------------------------------------------------------------------------
# Swift (Swift Package Manager)
# --------------------------------------------------------------------------

def _parse_swift(path: Path) -> dict:
    text = ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"language": "Swift", "manifest": "Package.swift"}

    frameworks: list[str] = []
    low = text.lower()
    if "vapor" in low:
        frameworks.append("Vapor")
    if "swiftui" in low:
        frameworks.append("SwiftUI")
    if "perfect" in low:
        frameworks.append("Perfect")

    versions: dict = {}
    m = re.search(r'swift-tools-version:(\d+\.\d+(?:\.\d+)?)', text)
    if m:
        versions["tools-version"] = m.group(1)

    return {
        "language": "Swift",
        "manifest": "Package.swift",
        "versions": versions,
        "frameworks": frameworks,
    }


# --------------------------------------------------------------------------
# Elixir (Mix)
# --------------------------------------------------------------------------

def _parse_mix(path: Path) -> dict:
    text = ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"language": "Elixir", "manifest": "mix.exs"}

    frameworks: list[str] = []
    if re.search(r"phoenix", text, re.IGNORECASE):
        frameworks.append("Phoenix")
    if re.search(r"ecto", text, re.IGNORECASE):
        frameworks.append("Ecto")

    versions: dict = {}
    m = re.search(r'elixir:\s*["\']([^"\']+)', text)
    if m:
        versions["elixir"] = m.group(1)

    return {
        "language": "Elixir",
        "manifest": "mix.exs",
        "versions": versions,
        "frameworks": frameworks,
    }
