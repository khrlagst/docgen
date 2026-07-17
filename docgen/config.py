from pathlib import Path
import os

DEFAULT_CONFIG_PATH = Path("~/.config/docgen/config.toml").expanduser()
PROJECT_CONFIG_DIR = ".docgen"
PROJECT_CONFIG_NAME = "config.toml"

# Provider-aware default model. When a user does not explicitly set
# `llm.model` (e.g. during onboarding), we fall back to a valid model ID for
# the chosen provider. OpenRouter requires the fully-qualified ID
# (`deepseek/deepseek-chat`); the bare `deepseek-chat` is ambiguous there.
DEFAULT_MODEL_BY_PROVIDER = {
    "openai": "gpt-4o",
    "anthropic": "claude-3-5-sonnet-latest",
        "gemini": "gemini-3.5-flash",
    "groq": "llama-3.3-70b-versatile",
    "mistral": "mistral-small-latest",
    "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "azure": "gpt-4o",
    "deepseek": "deepseek-chat",
    "openrouter": "deepseek/deepseek-chat",
    "ollama": "llama3.2",
}

# Curated, offline model catalog per provider. Used by `docgen models`, the
# onboarding flow, and to validate (warn, not fail) a user-supplied model ID.
# Azure deployment names and Ollama local model tags are arbitrary, so they are
# intentionally empty here.
MODELS_BY_PROVIDER = {
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4-turbo",
        "o1",
        "o3-mini",
    ],
    "anthropic": [
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
        "claude-3-opus-latest",
        "claude-3-haiku-20240307",
    ],
    "gemini": [
        "gemini-flash-latest",
        "gemini-pro-latest",
        "gemini-3-flash-preview",
        "gemini-3-pro-preview",
        "gemini-3.5-flash",
        "gemini-2.0-flash",
        "gemini-2.5-flash-lite",
    ],
    "groq": [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
        "gemma-2-9b-it",
    ],
    "mistral": [
        "mistral-large-latest",
        "mistral-small-latest",
        "open-mistral-7b",
        "codestral-latest",
    ],
    "together": [
        "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "deepseek-ai/DeepSeek-V3",
        "Qwen/Qwen2.5-72B-Instruct-Turbo",
        "mistralai/Mixtral-8x7B-Instruct-v0.1",
    ],
    "azure": [],
    "deepseek": [
        "deepseek-chat",
        "deepseek-reasoner",
    ],
    "openrouter": [
        "deepseek/deepseek-chat",
        "anthropic/claude-3.5-sonnet",
        "openai/gpt-4o",
        "google/gemini-pro-1.5",
    ],
    "ollama": [],
}


def default_model_for(provider: str) -> str:
    """Return a sensible default model ID for the given provider."""
    return DEFAULT_MODEL_BY_PROVIDER.get(provider, "deepseek-chat")


def validate_provider_model(provider: str, model: str | None) -> str | None:
    """Validate a provider/model pair.

    Returns a warning string if ``model`` is not in the curated catalog for
    ``provider`` (skips ``ollama``/``azure`` where names are arbitrary), or
    ``None`` when the pair looks fine. Never raises — providers add models
    constantly, so an unknown ID is a warning, not a hard error.
    """
    if not model:
        return None
    if provider in ("ollama", "azure"):
        return None
    catalog = MODELS_BY_PROVIDER.get(provider)
    if not catalog:
        return None
    if model in catalog:
        return None
    preview = ", ".join(catalog[:8])
    return (
        f"Model '{model}' is not in the known list for provider '{provider}'. "
        f"Known examples: {preview}. "
        f"Run `docgen models --provider {provider}` for the full list."
    )


# Schema of every known configuration key. Used by ``config set`` / ``config keys``
# to validate values and to document valid keys/choices in --help output.
CONFIG_KEY_REFERENCE: dict[str, dict[str, object]] = {
    "llm.provider": {
        "type": "choice",
        "default": "deepseek",
        "description": "Which LLM provider to use.",
        # "choices" is filled lazily from PROVIDER_REGISTRY.
    },
    "llm.model": {
        "type": "string",
        "default": "<provider default>",
        "description": "Model ID for the chosen provider. See `docgen models --provider <provider>`.",
    },
    "llm.api_key": {
        "type": "secret",
        "default": "—",
        "description": "API key for the provider (or set the DOCGEN_API_KEY env var).",
    },
    "llm.base_url": {
        "type": "url",
        "default": "—",
        "description": "API base URL (auto-set per provider; override only for proxies/Azure).",
    },
    "llm.temperature": {
        "type": "float",
        "default": 0.3,
        "description": "Sampling temperature, range 0.0–2.0.",
    },
    "llm.max_tokens": {
        "type": "int",
        "default": 8192,
        "description": "Max tokens returned per LLM response.",
    },
    "llm.timeout": {
        "type": "float",
        "default": 120.0,
        "description": "Per-request timeout in seconds.",
    },
    "templates.default": {
        "type": "choice",
        "default": "wiki",
        "choices": ["wiki", "manual", "readme"],
        "description": "Built-in template style.",
    },
    "templates.directory": {
        "type": "path",
        "default": "—",
        "description": "Directory of custom Jinja2 templates.",
    },
    "export.pdf_engine": {
        "type": "choice",
        "default": "weasyprint",
        "choices": ["weasyprint", "pandoc"],
        "description": "Engine used by `docgen export`.",
    },
    "export.stylesheet": {
        "type": "path",
        "default": "—",
        "description": "CSS file applied during PDF/HTML export.",
    },
    "generation.cache": {
        "type": "bool",
        "default": True,
        "description": "Cache AI responses to avoid re-generating identical sections.",
    },
    "generation.prompt_tokens_limit": {
        "type": "int",
        "default": 20000,
        "description": "Max tokens sent per LLM request.",
    },
    "generation.api_body_preview_lines": {
        "type": "int",
        "default": 15,
        "description": "Body preview lines for API reference sections.",
    },
}


def _populate_provider_choices() -> None:
    """Fill llm.provider choices from the live PROVIDER_REGISTRY."""
    from docgen.llm.factory import PROVIDER_REGISTRY

    CONFIG_KEY_REFERENCE["llm.provider"]["choices"] = list(PROVIDER_REGISTRY.keys())


_populate_provider_choices()


def _build_config_set_help() -> str:
    """Render the help text for ``docgen config set`` from CONFIG_KEY_REFERENCE."""
    lines = [
        "Set a configuration value using the dotted section.key form.",
        "",
        "Examples:",
        "  docgen config set llm.provider openai",
        "  docgen config set llm.model gpt-4o",
        "  docgen config set templates.default manual",
        "  docgen config set generation.cache false",
        "",
        "Known keys (use `docgen config keys` for the same list as a table):",
    ]
    for key, info in CONFIG_KEY_REFERENCE.items():  # noqa: B020
        default = info.get("default", "—")
        extra = ""
        if info.get("choices"):
            extra = "  one of: " + ", ".join(info["choices"])
        lines.append(f"  {key:<34} {info['type']:<7} default: {default}{extra}")
        lines.append(f"      {info['description']}")
    lines.append("")
    lines.append(
        "Note: choice keys (llm.provider, templates.default, export.pdf_engine) "
        "reject values outside the listed options."
    )
    return "\n".join(lines)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    if path.exists():
        import tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    return {}


def save_config(config: dict, path: Path = DEFAULT_CONFIG_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    import tomli_w
    with open(path, "wb") as f:
        tomli_w.dump(config, f)


def project_config_path(project_path: Path) -> Path:
    """Path to a project-local config: <project>/.docgen/config.toml."""
    return Path(project_path) / PROJECT_CONFIG_DIR / PROJECT_CONFIG_NAME


def effective_config_path(project_path: Path | None = None) -> Path:
    """Config to read: existing project-local file wins, else global."""
    if project_path is not None:
        p = project_config_path(project_path)
        if p.exists():
            return p
    return DEFAULT_CONFIG_PATH


def load_merged(project_path: Path | None = None) -> dict:
    """Load global config overlaid with project-local values.

    Project-local sections/keys override the global file so a project can
    carry its own provider/key without duplicating shared settings.
    Secrets stay in the project-local file, which init adds to .gitignore.
    """
    cfg = load_config(DEFAULT_CONFIG_PATH)
    if project_path is not None:
        p = project_config_path(project_path)
        if p.exists():
            proj = load_config(p)
            for key, value in proj.items():
                if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                    merged = dict(cfg[key])
                    merged.update(value)
                    cfg[key] = merged
                else:
                    cfg[key] = value
    return cfg



def get_default_config() -> dict:
    return {
        "llm": {
            "provider": os.getenv("DOCGEN_LLM_PROVIDER", "deepseek"),
            "api_key": os.getenv("DOCGEN_API_KEY", ""),
            "base_url": os.getenv("DOCGEN_BASE_URL", "https://api.deepseek.com"),
            "model": os.getenv("DOCGEN_MODEL", "deepseek-chat"),
            "max_tokens": int(os.getenv("DOCGEN_MAX_TOKENS", "8192")),
            "temperature": 0.3,
        },
        "templates": {
            "directory": str(Path.home() / ".config" / "docgen" / "templates"),
            "default": "wiki",
        },
        "export": {
            "pdf_engine": "weasyprint",
            "stylesheet": "",
        },
        "generation": {
            "cache": True,
        },
    }
