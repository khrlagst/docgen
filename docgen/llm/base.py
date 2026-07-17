from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 8192
    timeout: float = 120.0


@dataclass
class Completion:
    """Result of a provider call.

    Carries the generated ``content`` plus optional token ``usage``
    (``{"prompt_tokens", "completion_tokens", "total_tokens"}``). ``cached``
    marks responses served from the docgen cache so the engine can report them
    separately without a provider round-trip. Returning usage in the result
    (rather than mutating shared provider state) keeps parallel chunk
    generation race-free.
    """

    content: str
    usage: dict | None = None
    cached: bool = False


def _usage_from_response(response) -> dict | None:
    """Extract a normalized usage dict from an OpenAI-SDK chat completion."""
    raw = getattr(response, "usage", None)
    if raw is not None:
        return {
            "prompt_tokens": int(getattr(raw, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(raw, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(raw, "total_tokens", 0) or 0),
        }
    # Ollama's OpenAI-compatible endpoint reports eval counts at the top level
    # instead of in `usage`.
    pe = getattr(response, "prompt_eval_count", None)
    ec = getattr(response, "eval_count", None)
    if pe is not None or ec is not None:
        pe = int(pe or 0)
        ec = int(ec or 0)
        return {
            "prompt_tokens": pe,
            "completion_tokens": ec,
            "total_tokens": pe + ec,
        }
    return None


class LLMProvider(ABC):
    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> Completion:
        ...

    def generate_stream(self, system_prompt: str, user_prompt: str):
        yield self.generate(system_prompt, user_prompt).content
