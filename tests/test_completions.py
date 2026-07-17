import pytest

import click
from docgen.cli_complete import (
    complete_providers,
    complete_templates,
    complete_config_keys,
    complete_config_value,
)
from docgen.generator.engine import _robust_json_load, _strip_json_fences


class _FakeCtx:
    def __init__(self, params=None):
        self.params = params or {}

    @property
    def obj(self):
        return None


def test_complete_providers_filters_by_prefix():
    out = complete_providers(_FakeCtx(), [], "deep")
    assert out == ["deepseek"]


def test_complete_templates_lists_known():
    out = complete_templates(_FakeCtx(), [], "")
    assert set(out) == {"wiki", "manual", "readme"}


def test_complete_config_keys_lists_keys():
    out = complete_config_keys(_FakeCtx(), [], "llm.")
    assert "llm.provider" in out
    assert "llm.model" in out
    assert "templates.default" not in out
    # empty prefix returns all keys
    all_keys = complete_config_keys(_FakeCtx(), [], "")
    assert "llm.provider" in all_keys and "templates.default" in all_keys


def test_complete_config_value_uses_key_from_args():
    out = complete_config_value(_FakeCtx(), ["config", "set", "llm.provider"], "gem")
    assert "gemini" in out

    out2 = complete_config_value(_FakeCtx(), ["config", "set", "templates.default"], "w")
    assert out2 == ["wiki"]


def test_complete_config_value_open_value_returns_empty():
    assert complete_config_value(_FakeCtx(), ["config", "set", "llm.model"], "") == []


def test_robust_json_load_handles_unescaped_newlines():
    raw = '{\n"overview": "line1\nline2",\n"usage": "x"\n}'
    obj = _robust_json_load(raw)
    assert obj is not None
    assert "overview" in obj


def test_robust_json_load_handles_trailing_comma_and_prose():
    raw = 'Here is the doc:\n{\n  "overview": "x",\n  "usage": "y",\n}\nThanks!'
    obj = _robust_json_load(raw)
    assert obj is not None
    assert set(obj.keys()) >= {"overview", "usage"}


def test_robust_json_load_handles_fenced_block():
    fenced = "```json\n{\"a\": \"b\"}\n```"
    assert _strip_json_fences(fenced) == '{"a": "b"}'
    assert _robust_json_load(fenced) == {"a": "b"}


def test_robust_json_load_regex_salvages_broken_json():
    # Structurally broken JSON (unbalanced brace + stray text) that the normal
    # parser/repair cannot fix, but still contains the overview/features keys.
    broken = (
        'Sure! {"overview": "A trainer app\nwith two panes",\n'
        '"features": "Live preview, hints",\n extra junk here'
    )
    obj = _robust_json_load(broken)
    assert obj is not None
    assert obj["overview"] == "A trainer app\nwith two panes"
    assert obj["features"] == "Live preview, hints"


def test_robust_json_load_regex_unescapes_embedded_quotes():
    broken = '{"overview": "Use the "Preview" button", "features": "x"} broken'
    obj = _robust_json_load(broken)
    assert obj is not None
    assert obj["overview"] == 'Use the "Preview" button'
    assert obj["features"] == "x"


def test_robust_json_load_returns_none_on_garbage():
    assert _robust_json_load("not json at all") is None
