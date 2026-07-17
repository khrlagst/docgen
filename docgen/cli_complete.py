"""Shell completions and argument-value completers for docgen.

Typer/Click auto-complete command and option *names* once completion is
installed (``docgen --install-completion``), but the *values* of positional
args (e.g. ``config set llm.provider gemini``) need explicit completers. These
callbacks enumerate the dynamic, valid choices so the shell can hint them.

Wired into the CLI surface via ``shell_complete=`` on the relevant params.
"""

from typing import Any

from typer import _click
from docgen.config import CONFIG_KEY_REFERENCE
from docgen.llm.factory import PROVIDER_REGISTRY

TEMPLATE_CHOICES = ["wiki", "manual", "readme"]


def _filter(items: list[str], incomplete: str) -> list[str]:
    return [c for c in items if c.startswith(incomplete or "")]


def complete_providers(
    ctx: _click.Context, args: list[str], incomplete: str
) -> list[str]:
    return _filter(sorted(PROVIDER_REGISTRY.keys()), incomplete)


def complete_templates(
    ctx: _click.Context, args: list[str], incomplete: str
) -> list[str]:
    return _filter(TEMPLATE_CHOICES, incomplete)


def complete_config_keys(
    ctx: _click.Context, args: list[str], incomplete: str
) -> list[str]:
    return _filter(sorted(CONFIG_KEY_REFERENCE.keys()), incomplete)


def _config_key_from_args(args: list[str]) -> str:
    """The KEY token typed after ``config set`` (e.g. ``llm.provider``)."""
    if "set" in args:
        idx = args.index("set")
        if idx + 1 < len(args):
            return args[idx + 1]
    return ""


def complete_config_value(
    ctx: _click.Context, args: list[str], incomplete: str
) -> list[str]:
    """Complete the VALUE of ``config set <key> <value>`` based on the key."""
    key = _config_key_from_args(args)
    ref = CONFIG_KEY_REFERENCE.get(key)
    if ref and ref.get("choices"):
        pool = ref["choices"]
    elif key == "llm.provider":
        pool = sorted(PROVIDER_REGISTRY.keys())
    else:
        # Open-ended values (model, api_key, paths): nothing to suggest.
        return []
    return _filter(pool, incomplete)
