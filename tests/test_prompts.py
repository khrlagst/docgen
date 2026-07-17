from docgen.generator.prompts import build_prompt, build_api_prompt

BIG_PY = (
    "def big():\n"
    '    """Big function."""\n'
    "    UNIQUE_MARKER_LINE = 1\n"
    "    other = 2\n"
    "    return UNIQUE_MARKER_LINE\n"
    + "\n".join(f"    _pad = {i}" for i in range(5000))
    + "\n"
)


def test_build_api_prompt_stays_under_budget_and_keeps_body_preview():
    context = {"metadata": {"name": "P", "language": "Python", "include_api": True}}
    sys_prompt, user_prompt = build_api_prompt(
        context,
        {"mod.py": BIG_PY},
        prompt_tokens_limit=20000,
        body_preview_lines=15,
    )
    from docgen.generator.token_budget import estimate_tokens

    # Source was truncated to fit the budget and the body preview is present.
    assert estimate_tokens(user_prompt) <= 20000
    assert "UNIQUE_MARKER_LINE = 1" in user_prompt


def test_build_prompt_overview_strips_bodies_for_large_py():
    context = {
        "metadata": {
            "name": "P",
            "version": "1.0.0",
            "description": "d",
            "language": "Python",
            "include_api": False,
            "include_changelog": False,
            "include_guides": False,
        },
        "source_files": {"mod.py": BIG_PY},
        "git_info": None,
    }
    sys_prompt, user_prompt = build_prompt(context, "wiki", prompt_tokens_limit=20000)
    # Overview prompt keeps the signature/docstring but not the (private) body.
    assert "def big():" in user_prompt
    assert "UNIQUE_MARKER_LINE = 1" not in user_prompt


def test_build_prompt_includes_cli_surface_when_present():
    context = {
        "metadata": {"name": "P", "language": "Python"},
        "source_files": {},
        "cli_surface": "### Commands (`docgen`)\n- `docgen generate`",
    }
    _, user_prompt = build_prompt(context, "wiki", prompt_tokens_limit=20000)
    assert "CLI / API Surface (GROUND TRUTH" in user_prompt
    assert "docgen generate" in user_prompt


def test_build_prompt_omits_cli_surface_when_absent():
    context = {
        "metadata": {"name": "P", "language": "Python"},
        "source_files": {},
    }
    _, user_prompt = build_prompt(context, "wiki", prompt_tokens_limit=20000)
    assert "CLI / API Surface" not in user_prompt
