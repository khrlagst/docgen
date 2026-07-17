from docgen.config import (
    MODELS_BY_PROVIDER,
    DEFAULT_MODEL_BY_PROVIDER,
    default_model_for,
    validate_provider_model,
)
from docgen.llm.base import LLMConfig
from docgen.llm.factory import ProviderFactory, PROVIDER_REGISTRY
from docgen.cli import apply_llm_overrides, _fetch_live_models


EXPECTED_PROVIDERS = {
    "openai",
    "anthropic",
    "gemini",
    "groq",
    "mistral",
    "together",
    "azure",
    "deepseek",
    "openrouter",
    "ollama",
}


def test_registry_has_expected_providers():
    assert EXPECTED_PROVIDERS.issubset(set(PROVIDER_REGISTRY))


def test_factory_creates_every_provider_without_network():
    for name in PROVIDER_REGISTRY:
        provider = ProviderFactory.create(
            name,
            LLMConfig(api_key="test", base_url="", model=default_model_for(name)),
        )
        assert provider is not None
        # Ollama must be flagged local for the engine's concurrency bound.
        if name == "ollama":
            assert provider.local is True
        else:
            assert provider.local is False


def test_unknown_provider_raises():
    import pytest

    with pytest.raises(ValueError):
        ProviderFactory.create("nope", LLMConfig(api_key="x", base_url="", model="y"))


def test_catalog_and_defaults_cover_providers():
    for name in EXPECTED_PROVIDERS:
        assert name in MODELS_BY_PROVIDER
        assert default_model_for(name) == DEFAULT_MODEL_BY_PROVIDER[name]


def test_validate_provider_model_warns_on_unknown():
    warn = validate_provider_model("openai", "not-a-real-model")
    assert warn is not None
    assert "not-a-real-model" in warn


def test_validate_provider_model_silent_on_known():
    assert validate_provider_model("openai", "gpt-4o") is None


def test_validate_provider_model_skips_arbitrary_named_providers():
    # Ollama / Azure use arbitrary names, so no warning even for odd values.
    assert validate_provider_model("ollama", "my-custom-tag") is None
    assert validate_provider_model("azure", "my-deployment") is None


def test_apply_llm_overrides():
    config: dict = {"llm": {}}
    apply_llm_overrides(config, "groq", "llama-3.3-70b-versatile")
    assert config["llm"]["provider"] == "groq"
    assert config["llm"]["model"] == "llama-3.3-70b-versatile"

    # Provider given but model omitted -> only provider is set.
    config = {"llm": {"model": "keep-me"}}
    apply_llm_overrides(config, "openai", None)
    assert config["llm"]["provider"] == "openai"
    assert config["llm"]["model"] == "keep-me"


def test_fetch_live_models_no_key_returns_none(monkeypatch):
    # No API key configured and none in the environment -> graceful None.
    monkeypatch.setattr("os.getenv", lambda *a, **k: "")
    assert _fetch_live_models("openai", {}) is None
    # Unknown provider also yields None.
    assert _fetch_live_models("does-not-exist", {}) is None


def test_models_command_refresh_falls_back_to_curated(monkeypatch):
    from typer.testing import CliRunner
    from docgen.cli import app

    monkeypatch.setattr("docgen.cli._fetch_live_models", lambda p, c: None)
    monkeypatch.setattr("docgen.cli._load_cached_models", lambda: {})
    monkeypatch.setattr("docgen.cli._save_cached_models", lambda c: None)

    result = CliRunner().invoke(app, ["models", "--provider", "openai", "--refresh"])
    assert result.exit_code == 0
    assert "gpt-4o" in result.output
    assert "curated" in result.output


def test_models_command_refresh_shows_live_list(monkeypatch):
    from typer.testing import CliRunner
    from docgen.cli import app

    monkeypatch.setattr(
        "docgen.cli._fetch_live_models", lambda p, c: ["live-model-a", "live-model-b"]
    )
    monkeypatch.setattr("docgen.cli._load_cached_models", lambda: {})
    monkeypatch.setattr("docgen.cli._save_cached_models", lambda c: None)

    result = CliRunner().invoke(app, ["models", "--provider", "openai", "--refresh"])
    assert result.exit_code == 0
    assert "live-model-a" in result.output
    assert "live" in result.output


def test_models_command_plain_uses_curated(monkeypatch):
    from typer.testing import CliRunner
    from docgen.cli import app

    monkeypatch.setattr("docgen.cli._load_cached_models", lambda: {})

    result = CliRunner().invoke(app, ["models", "--provider", "openai"])
    assert result.exit_code == 0
    assert "gpt-4o" in result.output
