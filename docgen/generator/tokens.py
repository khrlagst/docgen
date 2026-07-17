from __future__ import annotations

from typing import Optional

CHARS_PER_TOKEN = 4


class TokenCounter:
    """Count tokens for a model, with a char/4 fallback when tiktoken is absent.

    Mirrors the `llm-engineering` TokenCounter pattern: prefer an exact
    tiktoken encoding, fall back to a cheap heuristic so callers never have to
    care whether the dependency is installed.
    """

    def __init__(self, model: str = "gpt-4"):
        self.model = model
        self.encoder = None
        try:
            import tiktoken

            try:
                self.encoder = tiktoken.encoding_for_model(model)
            except KeyError:
                self.encoder = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            self.encoder = None

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self.encoder is not None:
            return len(self.encoder.encode(text))
        return len(text) // CHARS_PER_TOKEN

    def count_messages(self, messages: list[dict]) -> int:
        total = 0
        for msg in messages:
            total += self.count(msg.get("content", "") or "")
            total += self.count(msg.get("role", ""))
        return total

    def truncate_to_limit(self, text: str, max_tokens: int) -> str:
        if self.encoder is not None:
            tokens = self.encoder.encode(text)
            if len(tokens) <= max_tokens:
                return text
            return self.encoder.decode(tokens[:max_tokens])
        # char/4 fallback: cap at max_tokens * 4 chars (approximate)
        limit = max_tokens * CHARS_PER_TOKEN
        if len(text) <= limit:
            return text
        return text[:limit]


_default_counter: Optional[TokenCounter] = None


def default_counter() -> TokenCounter:
    global _default_counter
    if _default_counter is None:
        _default_counter = TokenCounter()
    return _default_counter


def estimate_tokens(text: str) -> int:
    """Estimate tokens for arbitrary text using the shared counter."""
    return default_counter().count(text)
