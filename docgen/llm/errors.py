from __future__ import annotations

import re


def _short_inner(inner: str, limit: int = 180) -> str:
    """Collapse a raw provider message into a single clean line.

    Provider errors often arrive as a JSON blob (e.g. ``"Error code: 402 - {'error':
    {'message': ..., 'metadata': {'previous_errors': [...]}}}"``). Extract the human
    sentence and drop the embedded JSON/URLs so the message stays readable.
    """
    for raw in inner.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("{") or line.startswith("Error code:"):
            match = re.search(r"'message'\s*:\s*'([^']*)'", line)
            if not match:
                return ""
            line = match.group(1).strip()
        if len(line) > limit:
            line = line[:limit].rstrip() + "…"
        return line
    return ""


_PROMPT_LIMIT_RE = re.compile(
    r"Prompt tokens limit exceeded:\s*(\d+)\s*>\s*(\d+)", re.IGNORECASE
)


def parse_prompt_limit_from_402(message: str) -> int | None:
    """If ``message`` describes a provider prompt-token cap, return that cap (Y in
    ``X > Y``), else ``None``."""
    match = _PROMPT_LIMIT_RE.search(message or "")
    if match:
        return int(match.group(2))
    return None


def format_provider_error_text(e: Exception) -> str:
    """Turn a provider/LLM exception into a concise, actionable plain-text message.

    No Rich markup — safe to append to ``result.warnings`` or to wrap with styling
    elsewhere. Surfaces a short human explanation plus a fix, never the raw blob.
    """
    status = getattr(e, "status_code", None)
    body = getattr(e, "body", None)
    inner = ""
    if isinstance(body, dict):
        err = body.get("error", {})
        if isinstance(err, dict):
            inner = err.get("message", "") or ""
    if not inner:
        inner = str(getattr(e, "message", e)).strip()

    if status == 402:
        limit = parse_prompt_limit_from_402(inner)
        if limit is not None:
            return (
                f"Prompt too large ({limit}-token cap exceeded). "
                "Lower generation.prompt_tokens_limit or reduce source size."
            )
        if "credit" in inner.lower():
            return (
                "AI provider rejected the request: insufficient credits. "
                "Add credits at your provider's billing page, then retry."
            )
        if "max_token" in inner.lower():
            return (
                "AI provider rejected the request: requested max_tokens too high. "
                "Lower llm.max_tokens and retry."
            )
        return "AI provider rejected the request (402). Check credits/billing or lower the request size."

    if status == 401 or "api key" in inner.lower() or "auth" in inner.lower():
        return (
            "Authentication failed (401). Check your API key "
            "(DOCGEN_API_KEY or 'docgen config set llm.api_key <key>')."
        )
    if status == 404 or "model" in inner.lower():
        detail = _short_inner(inner)
        return (
            (f"Model not found (404). {detail} " if detail else "Model not found (404). ")
            + "Verify the model name ('docgen config set llm.model <name>')."
        )
    if status == 429:
        return "Rate limit exceeded (429). Wait a moment and retry, or reduce request size."
    if status == 400:
        detail = _short_inner(inner)
        return f"Bad request (400) from the provider. {detail}" if detail else "Bad request (400) from the provider."
    if status in (0, None) and "connection" in inner.lower():
        detail = _short_inner(inner)
        return (
            f"Could not connect to the provider. {detail} Check network and DOCGEN_BASE_URL."
            if detail
            else "Could not connect to the provider. Check network and DOCGEN_BASE_URL."
        )
    detail = _short_inner(inner)
    return f"AI generation failed: {detail}" if detail else "AI generation failed."
