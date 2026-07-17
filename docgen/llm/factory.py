from docgen.llm.base import LLMProvider, LLMConfig
from docgen.llm.generic import OpenAICompatibleProvider

# Provider metadata. Every entry is served by ``OpenAICompatibleProvider`` with a
# different base URL / headers / locality. ``base_url=None`` means it comes from
# the user's config (used by Azure, where the endpoint is deployment-specific).
PROVIDER_REGISTRY: dict[str, dict] = {
    "openai": {
        "display": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "auth_env": "OPENAI_API_KEY",
        "local": False,
        "default_headers": None,
    },
    "anthropic": {
        "display": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com/v1",
        "auth_env": "ANTHROPIC_API_KEY",
        "local": False,
        "default_headers": {"anthropic-version": "2023-06-01"},
    },
    "gemini": {
        "display": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "auth_env": "GEMINI_API_KEY",
        "local": False,
        "default_headers": None,
    },
    "groq": {
        "display": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "auth_env": "GROQ_API_KEY",
        "local": False,
        "default_headers": None,
    },
    "mistral": {
        "display": "Mistral",
        "base_url": "https://api.mistral.ai/v1",
        "auth_env": "MISTRAL_API_KEY",
        "local": False,
        "default_headers": None,
    },
    "together": {
        "display": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "auth_env": "TOGETHER_API_KEY",
        "local": False,
        "default_headers": None,
    },
    "azure": {
        "display": "Azure OpenAI",
        "base_url": None,
        "auth_env": "AZURE_OPENAI_API_KEY",
        "local": False,
        "default_headers": None,
    },
    "deepseek": {
        "display": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "auth_env": "DEEPSEEK_API_KEY",
        "local": False,
        "default_headers": None,
    },
    "openrouter": {
        "display": "OpenRouter (aggregator)",
        "base_url": "https://openrouter.ai/api/v1",
        "auth_env": "OPENROUTER_API_KEY",
        "local": False,
        "default_headers": None,
    },
    "ollama": {
        "display": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "auth_env": None,
        "local": True,
        "default_headers": None,
    },
}


class ProviderFactory:
    # Custom registered provider classes (extensibility). Bundled providers use
    # the registry + OpenAICompatibleProvider instead.
    _providers: dict[str, type[LLMProvider]] = {}

    @classmethod
    def register(cls, name: str, provider_cls: type[LLMProvider]):
        cls._providers[name] = provider_cls

    @classmethod
    def create(cls, name: str, config: LLMConfig) -> LLMProvider:
        if name not in PROVIDER_REGISTRY:
            available = ", ".join(sorted(PROVIDER_REGISTRY))
            raise ValueError(f"Unknown provider: {name}. Available: {available}")
        # Allow user-supplied custom classes to override the bundled behavior.
        if name in cls._providers:
            return cls._providers[name](config)
        meta = PROVIDER_REGISTRY[name]
        return OpenAICompatibleProvider(
            config,
            base_url=meta.get("base_url"),
            default_headers=meta.get("default_headers"),
            local=meta.get("local", False),
        )

    @classmethod
    def list_providers(cls) -> dict[str, dict]:
        return PROVIDER_REGISTRY
