import pytest
from unittest import mock

from docgen.config import load_config as real_load, save_config as real_save


class _Q:
    def __init__(self, value):
        self.value = value

    def ask(self):
        return self.value


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    import docgen.config as cfgmod

    monkeypatch.setattr(
        cfgmod, "load_config", lambda: real_load(path=cfg_path)
    )
    monkeypatch.setattr(
        cfgmod, "save_config", lambda c: real_save(c, path=cfg_path)
    )
    return cfg_path


def test_is_onboarded_false_by_default(tmp_config):
    from docgen.welcome import is_onboarded

    assert is_onboarded() is False


def test_run_onboarding_saves_consent(tmp_config, monkeypatch):
    import questionary
    from docgen.welcome import run_onboarding, is_onboarded

    captured = {"calls": []}

    def fake_select(*a, **k):
        captured["calls"].append(k.get("choices"))
        return _Q("openrouter")

    monkeypatch.setattr(questionary, "select", fake_select)
    monkeypatch.setattr(questionary, "text", lambda *a, default="", **k: _Q(default))
    monkeypatch.setattr(questionary, "password", lambda *a, **k: _Q("sk-test123"))
    monkeypatch.setattr(questionary, "confirm", lambda *a, default=False, **k: _Q(True))

    assert run_onboarding() is True
    assert is_onboarded() is True

    # The first select is the provider picker; its Choice values must be the
    # registry keys (display label -> provider key).
    from docgen.llm.factory import PROVIDER_REGISTRY

    provider_choices = captured["calls"][0]
    values = [c.value for c in provider_choices]
    assert values == list(PROVIDER_REGISTRY.keys())

    data = real_load(path=tmp_config)
    assert data["llm"]["provider"] == "openrouter"
    assert data["llm"]["api_key"] == "sk-test123"
    assert data["_meta"]["accepted_terms"] is True


def test_run_onboarding_declined(tmp_config, monkeypatch):
    import questionary
    from docgen.welcome import run_onboarding, is_onboarded

    monkeypatch.setattr(
        questionary, "select", lambda *a, **k: _Q("deepseek")
    )
    monkeypatch.setattr(questionary, "text", lambda *a, default="", **k: _Q(default))
    monkeypatch.setattr(questionary, "password", lambda *a, **k: _Q("sk-x"))
    monkeypatch.setattr(questionary, "confirm", lambda *a, default=False, **k: _Q(False))

    assert run_onboarding() is False
    assert is_onboarded() is False
