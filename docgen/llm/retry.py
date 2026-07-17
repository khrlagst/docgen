from __future__ import annotations

import tenacity
from openai import APIConnectionError, APITimeoutError, RateLimitError


def _wait_with_retry_after(retry_state: tenacity.RetryCallState) -> float:
    """Exponential backoff + jitter, but honor a Retry-After header if present.

    OpenAI/OpenRouter surface rate limits via `RateLimitError.response.headers`
    containing a `retry-after` (seconds) value; respecting it avoids hammering
    a provider that has explicitly asked us to back off.
    """
    outcome = retry_state.outcome
    exc = outcome.exception() if outcome else None
    if isinstance(exc, RateLimitError):
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None) if response else None
        if headers:
            retry_after = headers.get("retry-after")
            if retry_after:
                try:
                    return float(retry_after)
                except (TypeError, ValueError):
                    pass
    return tenacity.wait_exponential_jitter(initial=1, max=60)(retry_state)


# NOTE: `RateLimitError` is effectively inert for local models (e.g. Ollama),
# which do not emit a standards-compliant 429 + Retry-After header; their
# overload manifests as blocking/hangs/crashes instead. `APITimeoutError` and
# `APIConnectionError` are the useful retries for local instances (cold start,
# slow first token, server not yet up). Concurrency for local models is bounded
# separately by a semaphore in the generation engine.
RETRYABLE = (RateLimitError, APITimeoutError, APIConnectionError)


def with_retry(max_attempts: int = 3):
    """Retry transient provider errors with backoff; re-raise everything else.

    Retries only `RateLimitError`/`APITimeoutError`/`APIConnectionError` so that
    auth/4xx errors surface immediately through `format_provider_error`.
    """
    return tenacity.retry(
        retry=tenacity.retry_if_exception_type(RETRYABLE),
        wait=_wait_with_retry_after,
        stop=tenacity.stop_after_attempt(max_attempts),
        reraise=True,
    )
