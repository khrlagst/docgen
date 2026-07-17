"""Tests for source-watch regeneration (improvement #7)."""
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docgen.cli import run_generation, watch_source
from docgen.generator.engine import GenerationResult


def _make_config(api_key="test-key"):
    return {
        "project": {"name": "demo", "description": "demo project"},
        "llm": {"provider": "deepseek", "api_key": api_key, "model": "deepseek-chat"},
        "generation": {"cache": False},
        "templates": {},
    }


def test_run_generation_writes_docs(tmp_path, monkeypatch):
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")
    output_dir = tmp_path / "docs"

    fake_engine = MagicMock()
    fake_engine.generate.return_value = GenerationResult(
        files={"overview.md": "# Overview", "index.md": "# Home"}, warnings=[]
    )
    monkeypatch.setattr(
        "docgen.cli.GenerationEngine", lambda *a, **k: fake_engine
    )
    monkeypatch.setattr("docgen.cli.ProviderFactory", MagicMock())

    cfg = _make_config()
    result = run_generation(source_dir, output_dir, "wiki", cfg, show_status=False)

    assert result.files == {"overview.md": "# Overview", "index.md": "# Home"}
    assert (output_dir / "overview.md").read_text(encoding="utf-8") == "# Overview"
    assert (output_dir / "index.md").exists()
    fake_engine.generate.assert_called_once()


def test_watch_source_fires_on_file_change(tmp_path):
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    events = []

    observer = watch_source(source_dir, events.append, debounce=0.1)
    try:
        (source_dir / "module.py").write_text("x = 1\n", encoding="utf-8")

        deadline = time.time() + 5.0
        while not events and time.time() < deadline:
            time.sleep(0.05)

        # The created file should have produced at least one callback event.
        assert any(Path(e).name == "module.py" for e in events)
    finally:
        observer.stop()
        observer.join(timeout=3)


def test_watch_source_ignores_dotfiles(tmp_path):
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    events = []

    observer = watch_source(source_dir, events.append, debounce=0.05)
    try:
        (source_dir / ".hidden").write_text("secret\n", encoding="utf-8")
        (source_dir / ".cache").mkdir()
        (source_dir / ".cache" / "foo").write_text("a\n", encoding="utf-8")

        time.sleep(1.0)  # allow any spurious events to arrive

        assert not events
    finally:
        observer.stop()
        observer.join(timeout=3)
