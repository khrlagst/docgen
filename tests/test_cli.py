import pytest
from typer.testing import CliRunner
from docgen.cli import (
    app,
    _detect_source_dir,
    _resolve_project_path,
    build_llm_config,
    format_provider_error,
)
from docgen.config import default_model_for


@pytest.fixture
def runner():
    return CliRunner()


class _FakeProviderError(Exception):
    """Minimal stand-in for an OpenAI-SDK provider exception."""

    def __init__(self, status_code=None, body=None, message=None):
        self.status_code = status_code
        self.body = body
        self.message = message
        super().__init__(message or "")


def test_format_provider_error_402_is_concise_and_drops_blob():
    blob = (
        "Error code: 402 - {'error': {'message': \"This request requires more "
        "credits, or fewer max_tokens. You requested up to 8192 tokens, but can "
        "only afford 6296. To increase, visit https://openrouter.ai/keys/abc\", "
        "'code': 402, 'metadata': {'previous_errors': [{'code': 402}]}, "
        "'user_id': 'user_xyz'}}"
    )
    msg = format_provider_error(_FakeProviderError(status_code=402, message=blob))

    assert "insufficient credits" in msg.lower()
    assert "Add credits" in msg
    # The raw provider blob must never reach the user.
    assert "previous_errors" not in msg
    assert "openrouter.ai" not in msg
    assert "Error code: 402" not in msg


def test_format_provider_error_401_shows_auth_fix():
    msg = format_provider_error(
        _FakeProviderError(status_code=401, message="Incorrect API key provided")
    )
    assert "Authentication failed (401)" in msg
    assert "API key" in msg


def test_format_provider_error_404_trims_inner_note():
    msg = format_provider_error(
        _FakeProviderError(status_code=404, message="The model `x` does not exist")
    )
    assert "Model not found (404)" in msg
    assert "x` does not exist" in msg


def test_format_provider_error_429_rate_limit():
    msg = format_provider_error(
        _FakeProviderError(status_code=429, message="Too many requests")
    )
    assert "Rate limit exceeded (429)" in msg


def test_format_provider_error_blob_inner_is_collapsed():
    blob = "Error code: 500 - {'error': {'message': 'upstream failure', 'code': 500}}"
    msg = format_provider_error(_FakeProviderError(status_code=500, message=blob))
    assert "AI generation failed" in msg
    assert "upstream failure" in msg
    assert "Error code: 500" not in msg


def test_help(runner):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_generate_help(runner):
    result = runner.invoke(app, ["generate", "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_init_help(runner):
    result = runner.invoke(app, ["init", "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_refine_help(runner):
    result = runner.invoke(app, ["refine", "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_serve_help(runner):
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_export_help(runner):
    result = runner.invoke(app, ["export", "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_config_help(runner):
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_generate_requires_api_key(runner, monkeypatch):
    monkeypatch.setattr("docgen.cli.load_config", lambda: {"project": {"name": "X"}})
    monkeypatch.setattr("docgen.cli.is_onboarded", lambda: True)
    result = runner.invoke(app, ["generate"])
    assert result.exit_code == 1


def test_detect_source_dir_prefers_existing_source_folder(tmp_path):
    (tmp_path / "src").mkdir()
    assert _detect_source_dir(tmp_path) == tmp_path / "src"


def test_detect_source_dir_falls_back_to_project_root(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    assert _detect_source_dir(tmp_path) == tmp_path


def test_resolve_project_path_uses_current_directory_when_missing(tmp_path):
    resolved = _resolve_project_path(None, cwd=tmp_path)
    assert resolved == tmp_path


def test_config_show(runner):
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0


def test_config_show_masks_secret(runner, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["config", "set", "llm.api_key", "SK_ABCEFGHIJ"])
    result = runner.invoke(app, ["config", "show"])
    assert "SK_ABCEFGHIJ" not in result.output
    assert "****GHIJ" in result.output


def test_config_set_rejects_unknown_provider(runner, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["config", "set", "llm.provider", "bogus"])
    assert result.exit_code == 1
    assert "Invalid value" in result.output
    assert "openai" in result.output


def test_config_set_rejects_unknown_template(runner, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["config", "set", "templates.default", "ebook"])
    assert result.exit_code == 1
    assert "Invalid value" in result.output
    assert "wiki" in result.output


def test_config_set_warns_on_bad_bool(runner, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["config", "set", "generation.cache", "maybe"])
    assert result.exit_code == 0
    assert "expects true/false" in result.output


def test_config_set_accepts_valid_provider(runner, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["config", "set", "llm.provider", "openai"])
    assert result.exit_code == 0
    assert "not a valid value" not in result.output


def test_config_keys_lists_known_keys(runner):
    result = runner.invoke(app, ["config", "keys"])
    assert result.exit_code == 0
    assert "llm.provider" in result.output
    assert "templates.default" in result.output
    assert "generation.cache" in result.output


def test_config_set_help_lists_known_keys(runner):
    result = runner.invoke(app, ["config", "set", "--help"])
    assert result.exit_code == 0
    assert "Known keys" in result.output
    assert "llm.provider" in result.output
    assert "templates.default" in result.output


def test_models_providers_flag_lists_providers(runner):
    result = runner.invoke(app, ["models", "--providers"])
    assert result.exit_code == 0
    assert "Supported LLM providers" in result.output
    assert "openai" in result.output
    assert "deepseek" in result.output


def test_models_provider_unknown_is_error(runner):
    result = runner.invoke(app, ["models", "--provider", "nope"])
    assert result.exit_code == 1
    assert "Unknown provider" in result.output




@pytest.mark.parametrize("cmd", [
    "init", "generate", "refine", "serve", "export",
])
def test_all_commands_have_help(runner, cmd):
    result = runner.invoke(app, [cmd, "--help"])
    assert result.exit_code == 0


def test_default_model_for_known_providers():
    assert default_model_for("deepseek") == "deepseek-chat"
    assert default_model_for("openrouter") == "deepseek/deepseek-chat"
    assert default_model_for("ollama") == "llama3.2"
    # unknown provider falls back to deepseek-chat
    assert default_model_for("unknown") == "deepseek-chat"


def test_build_llm_config_uses_provider_default_model():
    # No model set -> provider-appropriate default (OpenRouter needs the
    # qualified ID, not the ambiguous bare 'deepseek-chat').
    cfg = build_llm_config({"llm": {"provider": "openrouter", "api_key": "x"}})
    assert cfg.model == "deepseek/deepseek-chat"

    cfg = build_llm_config({"llm": {"provider": "deepseek", "api_key": "x"}})
    assert cfg.model == "deepseek-chat"


def test_build_llm_config_respects_explicit_model():
    cfg = build_llm_config(
        {"llm": {"provider": "openrouter", "api_key": "x", "model": "anthropic/claude-3.5-sonnet"}}
    )
    assert cfg.model == "anthropic/claude-3.5-sonnet"
