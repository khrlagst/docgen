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


# --- Broader ecosystem detection ------------------------------------------


def test_pubspec_flutter_detection(tmp_path: Path):
    (tmp_path / "pubspec.yaml").write_text(
        "name: myapp\n"
        "environment:\n"
        "  sdk: '>=3.0.0 <4.0.0'\n"
        "dependencies:\n"
        "  flutter:\n"
        "    sdk: flutter\n"
        "  flutter_riverpod: ^2.0.0\n",
        encoding="utf-8",
    )
    stack = detect_manifest(tmp_path)
    assert stack["language"] == "Flutter"
    assert stack["manifest"] == "pubspec.yaml"
    assert stack["versions"]["sdk"].startswith(">=3.0.0")
    assert "Riverpod" in stack["frameworks"]


def test_pubspec_plain_dart(tmp_path: Path):
    (tmp_path / "pubspec.yaml").write_text(
        "name: tool\n"
        "environment:\n"
        "  sdk: '>=3.0.0 <4.0.0'\n",
        encoding="utf-8",
    )
    stack = detect_manifest(tmp_path)
    assert stack["language"] == "Dart"


def test_gradle_kotlin_springboot(tmp_path: Path):
    (tmp_path / "build.gradle.kts").write_text(
        "plugins {\n"
        "  kotlin(\"jvm\") version \"1.9.0\"\n"
        "  id(\"org.springframework.boot\") version \"3.2.0\"\n"
        "}\n"
        "java { sourceCompatibility = JavaVersion.VERSION_17 }\n",
        encoding="utf-8",
    )
    stack = detect_manifest(tmp_path)
    assert stack["language"] == "Kotlin"
    assert "Spring Boot" in stack["frameworks"]
    assert stack["versions"]["java"] == "17"


def test_pom_java_spring(tmp_path: Path):
    (tmp_path / "pom.xml").write_text(
        "<project>\n"
        "  <properties>\n"
        "    <java.version>21</java.version>\n"
        "    <spring-boot.version>3.2.0</spring-boot.version>\n"
        "  </properties>\n"
        "  <dependencies>\n"
        "    <dependency><groupId>org.springframework.boot</groupId></dependency>\n"
        "  </dependencies>\n"
        "</project>\n",
        encoding="utf-8",
    )
    stack = detect_manifest(tmp_path)
    assert stack["language"] == "Java"
    assert "Spring Boot" in stack["frameworks"]
    assert stack["versions"]["java"] == "21"


def test_composer_laravel(tmp_path: Path):
    (tmp_path / "composer.json").write_text(
        json.dumps({
            "name": "app",
            "require": {"php": "^8.2", "laravel/framework": "^11.0"},
        }),
        encoding="utf-8",
    )
    stack = detect_manifest(tmp_path)
    assert stack["language"] == "PHP"
    assert "Laravel" in stack["frameworks"]
    assert stack["versions"]["php"] == "^8.2"


def test_gemfile_rails(tmp_path: Path):
    (tmp_path / "Gemfile").write_text(
        "source 'https://rubygems.org'\n"
        "ruby '3.3.0'\n"
        "gem 'rails', '~> 7.1'\n"
        "gem 'rspec'\n",
        encoding="utf-8",
    )
    stack = detect_manifest(tmp_path)
    assert stack["language"] == "Ruby"
    assert "Rails" in stack["frameworks"]
    assert stack["versions"]["ruby"] == "3.3.0"


def test_csproj_aspnet_core(tmp_path: Path):
    (tmp_path / "MyApp.csproj").write_text(
        "<Project Sdk=\"Microsoft.NET.Sdk.Web\">\n"
        "  <PropertyGroup>\n"
        "    <TargetFramework>net8.0</TargetFramework>\n"
        "    <LangVersion>latest</LangVersion>\n"
        "  </PropertyGroup>\n"
        "</Project>\n",
        encoding="utf-8",
    )
    stack = detect_manifest(tmp_path)
    assert stack["language"] == "C#"
    assert "ASP.NET Core" in stack["frameworks"]
    assert stack["versions"]["target"] == "net8.0"


def test_package_swift_vapor(tmp_path: Path):
    (tmp_path / "Package.swift").write_text(
        "// swift-tools-version:5.9\n"
        "import PackageDescription\n"
        "let package = Package(\n"
        "  dependencies: [.package(url: \"https://github.com/vapor/vapor\", from: \"4.0.0\")]\n"
        ")\n",
        encoding="utf-8",
    )
    stack = detect_manifest(tmp_path)
    assert stack["language"] == "Swift"
    assert "Vapor" in stack["frameworks"]
    assert stack["versions"]["tools-version"] == "5.9"


def test_mix_exs_phoenix(tmp_path: Path):
    (tmp_path / "mix.exs").write_text(
        "defmodule MyApp.MixProject do\n"
        "  use Mix.Project\n"
        "  def project, do: [app: :my_app, elixir: \"~> 1.15\"]\n"
        "  defp deps, do: [{:phoenix, \"~> 1.7\"}, {:ecto, \"~> 3.10\"}]\n"
        "end\n",
        encoding="utf-8",
    )
    stack = detect_manifest(tmp_path)
    assert stack["language"] == "Elixir"
    assert "Phoenix" in stack["frameworks"]
    assert stack["versions"]["elixir"] == "~> 1.15"
