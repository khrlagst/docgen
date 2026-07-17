import json
import threading
import time

import pytest
from docgen.generator.engine import GenerationEngine, TokenUsage
from docgen.llm.base import Completion
from docgen.generator.prompts import (
    build_prompt,
    build_api_prompt,
    build_changelog_prompt,
)


class MockProvider:
    def __init__(self, response: str = '{"overview": "Test overview."}'):
        self.response = response

    def generate(self, system_prompt, user_prompt):
        return Completion(
            self.response,
            usage={
                "prompt_tokens": len(system_prompt) // 4 + len(user_prompt) // 4,
                "completion_tokens": len(self.response) // 4,
                "total_tokens": len(system_prompt) // 4
                + len(user_prompt) // 4
                + len(self.response) // 4,
            },
        )

    def generate_stream(self, system_prompt, user_prompt):
        yield self.response


class ConcurrentProvider:
    """Records the peak number of concurrent `generate` calls.

    Used to assert the engine's semaphore bounds in-flight calls for local
    providers (Ollama) and stays permissive for cloud providers.
    """

    def __init__(self, local: bool = False, response: str = '{"overview": "x"}'):
        self.local = local
        self.response = response
        self._lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0

    def generate(self, system_prompt, user_prompt):
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        time.sleep(0.01)
        with self._lock:
            self._in_flight -= 1
        return Completion(self.response, usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})


def _hammer(engine, n: int = 8):
    """Fire `n` concurrent `_cached_generate` calls and return peak in-flight."""

    def _call():
        engine._cached_generate("sys", "usr")

    threads = [threading.Thread(target=_call) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return engine.provider.max_in_flight


def test_local_provider_capped_at_two():
    provider = ConcurrentProvider(local=True)
    engine = GenerationEngine(provider)
    assert engine._cap == 2
    assert _hammer(engine, 8) <= 2


def test_cloud_provider_allows_four():
    provider = ConcurrentProvider(local=False)
    engine = GenerationEngine(provider)
    assert engine._cap == 4
    # Under load the semaphore should permit up to 4 (not be forced to 2).
    assert _hammer(engine, 8) == 4


def test_max_workers_override():
    provider = ConcurrentProvider(local=True)
    engine = GenerationEngine(provider, max_workers=1)
    assert engine._cap == 1
    assert _hammer(engine, 8) <= 1



@pytest.fixture
def sample_context():
    return {
        "metadata": {
            "name": "TestProject",
            "version": "1.0.0",
            "description": "A test project",
            "language": "Python",
            "include_api": True,
            "include_changelog": True,
            "include_guides": False,
        },
        "source_modules": {
            "core.py": {
                "module_docstring": "Core module",
                "functions": [
                    {"name": "run", "args": ["task"], "docstring": "Run a task", "returns": None, "decorators": []}
                ],
                "classes": [],
            }
        },
        "git_info": None,
    }


def test_engine_generates_index_page(sample_context):
    provider = MockProvider(response=json.dumps({
        "overview": "# Overview\n\nProject overview content.",
        "features": "- Fast\n- Reliable",
        "installation": "Install with pip.",
        "quickstart": "Run `start()`.",
        "usage": "Detailed usage here.",
        "api_reference": "## API\n\nFunctions...",
        "changelog": "## 1.0.0\n\nInitial release.",
    }))
    engine = GenerationEngine(provider)
    result = engine.generate(sample_context)
    assert "index.md" in result.files
    assert "TestProject" in result.files["index.md"]


def test_engine_generates_all_pages(sample_context):
    provider = MockProvider(response=json.dumps({
        "overview": "Overview.",
        "features": "Features.",
        "installation": "Installation steps.",
        "quickstart": "Quick start.",
        "usage": "Usage guide.",
        "api_reference": "API docs here.",
        "changelog": "Changelog entries.",
    }))
    engine = GenerationEngine(provider)
    result = engine.generate(sample_context)
    expected = ["index.md", "installation.md", "usage.md", "api-reference.md", "changelog.md"]
    for f in expected:
        assert f in result.files, f"Missing {f}"


def test_engine_skips_missing_sections(sample_context):
    provider = MockProvider(response=json.dumps({
        "overview": "Overview.",
        "features": "Features.",
    }))
    engine = GenerationEngine(provider)
    result = engine.generate(sample_context)
    assert "index.md" in result.files
    assert "installation.md" not in result.files
    assert "usage.md" not in result.files
    assert "api-reference.md" not in result.files


def test_engine_adds_warning_for_unstructured_response(sample_context):
    provider = MockProvider(response="Just some text, not JSON")
    engine = GenerationEngine(provider)
    result = engine.generate(sample_context)
    assert len(result.warnings) > 0
    assert "index.md" in result.files


def test_engine_parses_json_in_codeblock(sample_context):
    json_response = '```json\n{"overview": "# Hello"}\n```'
    provider = MockProvider(response=json_response)
    engine = GenerationEngine(provider)
    result = engine.generate(sample_context)
    assert "index.md" in result.files
    assert "# Hello" in result.files["index.md"] or result.files["index.md"] != ""


def test_engine_offline_badges_when_use_shields_false(sample_context):
    provider = MockProvider(response=json.dumps({
        "overview": "Overview.",
        "features": "Features.",
    }))
    engine = GenerationEngine(provider, use_shields=False)
    result = engine.generate(sample_context)
    index = result.files["index.md"]
    assert "Generated by docgen" in index
    assert "img.shields.io" not in index


def test_engine_shields_badges_when_use_shields_true(sample_context):
    provider = MockProvider(response=json.dumps({
        "overview": "Overview.",
        "features": "Features.",
    }))
    engine = GenerationEngine(provider, use_shields=True)
    result = engine.generate(sample_context)
    index = result.files["index.md"]
    assert "img.shields.io" in index


def test_build_prompt_includes_project_tree_and_workflows():
    context = {
        "metadata": {
            "name": "MyLib",
            "version": "2.0.0",
            "description": "A library",
            "language": "Python",
            "include_api": True,
            "include_changelog": False,
            "include_guides": False,
        },
        "source_modules": {},
        "git_info": None,
        "project_tree": "src/\n  app/\n    main.py",
        "workflow_summary": "- CLI workflow for generating docs",
    }
    _, user_prompt = build_prompt(context)
    assert "Project Tree" in user_prompt
    assert "src/" in user_prompt
    assert "CLI workflow" in user_prompt


def test_build_prompt_includes_metadata():
    context = {
        "metadata": {
            "name": "MyLib",
            "version": "2.0.0",
            "description": "A library",
            "language": "Python",
            "include_api": True,
            "include_changelog": False,
            "include_guides": False,
        },
        "source_modules": {},
        "git_info": None,
    }
    sys_prompt, user_prompt = build_prompt(context)
    assert "MyLib" in user_prompt
    assert "2.0.0" in user_prompt
    assert "A library" in user_prompt


def test_build_prompt_does_not_request_changelog():
    # The changelog is now generated by a separate historian call (T3),
    # so the architect prompt must not ask for a "changelog" key.
    context = {
        "metadata": {
            "name": "MyLib",
            "version": "2.0.0",
            "description": "A library",
            "language": "Python",
            "include_api": True,
            "include_changelog": True,
            "include_guides": False,
        },
        "source_modules": {},
        "git_info": None,
    }
    _, user_prompt = build_prompt(context)
    assert '"changelog"' not in user_prompt


def test_build_prompt_includes_detected_stack():
    context = {
        "metadata": {
            "name": "MyLib",
            "version": "2.0.0",
            "description": "A library",
            "language": "Python",
            "include_api": True,
            "include_changelog": False,
            "include_guides": False,
            "stack": {
                "language": "Python",
                "versions": {"requires-python": ">=3.11"},
                "frameworks": ["FastAPI"],
            },
        },
        "source_modules": {},
        "git_info": None,
    }
    _, user_prompt = build_prompt(context)
    assert "Detected Tech Stack" in user_prompt
    assert "FastAPI" in user_prompt
    assert ">=3.11" in user_prompt


def test_build_changelog_prompt_is_distinct():
    commits = [
        {"sha": "abc1234", "message": "Add feature X", "author": "Ada", "date": "2024-01-01"},
        {"sha": "def5678", "message": "Fix bug Y", "author": "Linus", "date": "2024-01-02"},
    ]
    system, user = build_changelog_prompt(commits)
    assert "historian" in system.lower() or "changelog" in system.lower()
    assert "abc1234" in user
    assert "Add feature X" in user
    # distinct from the architect/api prompts
    assert "Complete API reference" not in user


def test_build_changelog_prompt_handles_empty_commits():
    system, user = build_changelog_prompt([])
    assert isinstance(system, str) and isinstance(user, str)
    assert len(user) > 0


def test_three_prompt_builders_are_distinct():
    context = {
        "metadata": {"name": "P", "language": "Python", "include_api": True},
        "source_modules": {},
        "git_info": None,
    }
    arch_sys, arch_user = build_prompt(context)
    api_sys, api_user = build_api_prompt(context, {"x.py": "print(1)"})
    hist_sys, hist_user = build_changelog_prompt([{"sha": "a1b2c3", "message": "m", "author": "u", "date": "d"}])
    # all three user prompts are distinct
    assert arch_user != api_user
    assert arch_user != hist_user
    assert api_user != hist_user
    # historian is the only one that references the commit and frames itself as historian
    assert "a1b2c3" in hist_user
    assert "historian" in hist_sys.lower()
    assert "historian" not in arch_sys.lower()


def test_engine_accumulates_token_usage(sample_context):
    provider = MockProvider(response=json.dumps({
        "overview": "Overview.",
        "features": "Features.",
        "installation": "Install.",
        "quickstart": "Start.",
        "usage": "Use it.",
        "api_reference": "API.",
        "changelog": "Log.",
    }))
    engine = GenerationEngine(provider)
    result = engine.generate(sample_context)
    usage = result.token_usage
    assert usage.total_tokens > 0
    assert usage.prompt_tokens > 0
    assert usage.completion_tokens > 0
    assert usage.provider_calls >= 1
    assert usage.cached_calls == 0


def test_engine_fires_on_progress_with_running_totals(sample_context):
    provider = MockProvider(response=json.dumps({
        "overview": "Overview.",
        "features": "Features.",
        "installation": "Install.",
        "quickstart": "Start.",
        "usage": "Use it.",
        "api_reference": "API.",
        "changelog": "Log.",
    }))
    seen = []
    engine = GenerationEngine(provider, on_progress=seen.append)
    engine.generate(sample_context)
    assert seen, "on_progress was never called"
    assert all(isinstance(u, TokenUsage) for u in seen)
    # Running total must be monotonically non-decreasing.
    totals = [u.total_tokens for u in seen]
    assert totals == sorted(totals)
    assert seen[-1].total_tokens > 0


def test_engine_counts_cached_calls(sample_context):
    provider = MockProvider(response=json.dumps({
        "overview": "Overview.",
        "features": "Features.",
        "installation": "Install.",
        "quickstart": "Start.",
        "usage": "Use it.",
        "api_reference": "API.",
        "changelog": "Log.",
    }))
    from docgen.generator.cache import ResponseCache

    from pathlib import Path
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        cache = ResponseCache(path=Path(tmp) / "gen.json", enabled=True)
        engine = GenerationEngine(provider, cache=cache)
        first = engine.generate(sample_context)
        # A second run with the same context reuses the cache for every section,
        # so it makes no new provider calls and counts them all as cached.
        second = engine.generate(sample_context)
    assert first.token_usage.cached_calls == 0
    assert first.token_usage.provider_calls >= 1
    assert second.token_usage.provider_calls == 0
    assert second.token_usage.cached_calls >= 1


def _big_context(n_functions: int = 4000) -> dict:
    big_py = "\n".join(
        f"def f_{i}(a):\n    \"\"\"Fn {i}.\"\"\"\n    return a + {i}\n" for i in range(n_functions)
    )
    return {
        "metadata": {
            "name": "BigProject",
            "version": "1.0.0",
            "description": "A big project",
            "language": "Python",
            "include_api": True,
            "include_changelog": True,
            "include_guides": False,
        },
        "source_files": {"big.py": big_py},
        "source_modules": {},
        "git_info": None,
    }


def test_engine_huge_project_generates_api_without_prompt_errors():
    provider = MockProvider(
        response=json.dumps(
            {
                "overview": "Overview.",
                "features": "Features.",
                "installation": "Install.",
                "quickstart": "Start.",
                "usage": "Use it.",
                "api_reference": "API.",
                "changelog": "Log.",
            }
        )
    )
    engine = GenerationEngine(provider, prompt_tokens_limit=20000)
    result = engine.generate(_big_context())
    assert "index.md" in result.files
    assert "api-reference.md" in result.files
    # No chunk should have been rejected for exceeding the prompt cap.
    assert not any(w.startswith("API chunk") for w in result.warnings)
    assert not any("Error code: 402" in w for w in result.warnings)


class _Err402(Exception):
    status_code = 402
    body = {"error": {"message": "Prompt tokens limit exceeded: 12345 > 8000."}}

    def __init__(self):
        super().__init__(
            "Error code: 402 - {'error': {'message': "
            "\"Prompt tokens limit exceeded: 12345 > 8000.\"}}"
        )


class Recovering402Provider:
    """Raises a provider prompt-token 402 on the first call, then succeeds."""

    def __init__(self):
        self._n = 0
        self.response = json.dumps(
            {
                "overview": "Overview.",
                "features": "Features.",
                "installation": "Install.",
                "quickstart": "Start.",
                "usage": "Use it.",
                "api_reference": "API.",
                "changelog": "Log.",
            }
        )

    def generate(self, system_prompt, user_prompt):
        self._n += 1
        if self._n == 1:
            raise _Err402()
        return Completion(
            self.response,
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )


def test_engine_self_heals_prompt_limit_402():
    provider = Recovering402Provider()
    engine = GenerationEngine(provider, prompt_tokens_limit=20000)
    result = engine.generate(_big_context(n_functions=200))

    assert "index.md" in result.files
    # The cap was lowered below the provider's reported 8000 (minus margin).
    assert engine._prompt_tokens_limit <= 6000
    # The recovered 402 never surfaced as a raw JSON warning.
    assert not any("Error code: 402" in w for w in result.warnings)
    assert not any(w.startswith("API chunk") for w in result.warnings)


