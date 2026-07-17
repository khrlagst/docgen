"""Tests for the opt-in semantic cache and streaming (improvement #4)."""
from pathlib import Path

from docgen.generator.semantic_cache import SemanticCache, _cosine, _embed


def test_semantic_cache_hits_on_whitespace_edit(tmp_path):
    store = tmp_path / "semantic.jsonl"
    cache = SemanticCache(store_path=store, enabled=True, threshold=0.85)

    prompt = "generate api docs for def add(a, b): return a + b"
    cache.set(prompt, "ADD_DOC")

    # Trivial edit: extra spaces / word order reshuffle should still match.
    near = "generate api docs for  def add(a,b): return a+b"
    assert cache.get(near) == "ADD_DOC"


def test_semantic_cache_misses_on_unrelated_prompt(tmp_path):
    store = tmp_path / "semantic.jsonl"
    cache = SemanticCache(store_path=store, enabled=True, threshold=0.85)

    cache.set("document the database connection pool", "DB_DOC")
    assert cache.get("explain the http rate limiter middleware") is None


def test_semantic_cache_disabled_by_default(tmp_path):
    store = tmp_path / "semantic.jsonl"
    cache = SemanticCache(store_path=store, enabled=False)
    cache.set("anything", "X")
    assert cache.get("anything") is None


def test_semantic_cache_persists_across_instances(tmp_path):
    store = tmp_path / "semantic.jsonl"
    SemanticCache(store_path=store, enabled=True).set("prompt one", "RES_ONE")

    reopened = SemanticCache(store_path=store, enabled=True)
    assert reopened.get("prompt one") == "RES_ONE"


def test_engine_semantic_layer_returns_cached_response(monkeypatch):
    from docgen.generator.engine import GenerationEngine

    provider = type("P", (), {})()
    provider.generate = lambda s, u: (_ for _ in ()).throw(
        AssertionError("LLM should not be called on semantic hit")
    )
    provider.generate_stream = lambda s, u: (_ for _ in ()).throw(
        AssertionError("should not stream")
    )

    cache = SemanticCache(
        store_path=Path("/tmp/semantic_test.jsonl"), enabled=True, threshold=0.85
    )
    cache.set("build docs for main module", "CACHED_RESPONSE")

    engine = GenerationEngine(
        provider, template_name="wiki", cache=None, semantic_cache=cache
    )
    cached = engine._cached_generate("sys", "build docs for main module")
    assert cached.content == "CACHED_RESPONSE"
    assert cached.cached is True
