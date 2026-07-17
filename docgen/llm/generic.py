from openai import OpenAI
from docgen.llm.base import LLMProvider, LLMConfig, Completion, _usage_from_response
from docgen.llm.retry import with_retry


class OpenAICompatibleProvider(LLMProvider):
    """A provider that speaks the OpenAI chat-completions API.

    Every bundled provider (OpenAI, Anthropic, Gemini, Groq, Mistral, Together,
    Azure, DeepSeek, OpenRouter, Ollama) is OpenAI-compatible; they differ only
    in base URL, optional default headers, and whether they run locally. A single
    class therefore serves them all from the ``PROVIDER_REGISTRY`` in
    :mod:`docgen.llm.factory`.

    NOTE: Anthropic's OpenAI-compatible endpoint is in beta, so its
    ``default_headers`` carries the ``anthropic-version`` pin. If that path ever
    breaks, add the ``anthropic`` SDK and a dedicated provider class.
    """

    def __init__(
        self,
        config: LLMConfig,
        base_url: str | None = None,
        default_headers: dict | None = None,
        local: bool = False,
    ):
        super().__init__(config)
        self.local = local
        if local:
            api_key = "ollama"
            base_url = base_url or "http://localhost:11434/v1"
        else:
            api_key = config.api_key
            base_url = base_url or config.base_url

        kwargs = dict(api_key=api_key, base_url=base_url, timeout=config.timeout)
        if default_headers:
            kwargs["default_headers"] = default_headers
        self.client = OpenAI(**kwargs)

    @with_retry()
    def generate(self, system_prompt: str, user_prompt: str) -> Completion:
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        return Completion(
            response.choices[0].message.content,
            usage=_usage_from_response(response),
        )
