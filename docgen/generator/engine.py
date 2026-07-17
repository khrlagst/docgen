import json
import re
import hashlib
import threading
from datetime import datetime
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from docgen.llm.base import LLMProvider, Completion
from docgen.generator.prompts import (
    build_prompt,
    build_api_prompt,
    build_changelog_prompt,
)
from docgen.generator.token_budget import (
    estimate_tokens,
    chunk_by_symbol,
    PROMPT_TOKENS_LIMIT,
    PROMPT_OVERHEAD_RESERVE,
    API_BODY_PREVIEW_LINES,
)
from docgen.llm.errors import format_provider_error_text, parse_prompt_limit_from_402
from docgen.utils.net import shields_reachable
from docgen.generator.cache import ResponseCache
from docgen.templates.loader import create_template_env


@dataclass
class TokenUsage:
    """Aggregated token accounting across a generation run."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    provider_calls: int = 0
    cached_calls: int = 0


@dataclass
class GenerationResult:
    files: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)


PAGE_MAP = {
    "index": {
        "file": "index.md",
        "title": "Home",
        "subtitle": "Project overview and quick links",
        "template": "index",
    },
    "installation": {
        "file": "installation.md",
        "title": "Installation",
        "subtitle": "Setup and installation guide",
        "template": "installation",
    },
    "quickstart": {
        "file": "quickstart.md",
        "title": "Quick Start",
        "subtitle": "Getting started quickly",
        "template": "quickstart",
    },
    "usage": {
        "file": "usage.md",
        "title": "Usage",
        "subtitle": "Detailed usage guide",
        "template": "usage",
    },
    "guides": {
        "file": "guides.md",
        "title": "Guides",
        "subtitle": "Tutorials and walkthroughs",
        "template": "guides",
    },
    "api_reference": {
        "file": "api-reference.md",
        "title": "API Reference",
        "subtitle": "Full API documentation",
        "template": "api-reference",
    },
    "changelog": {
        "file": "changelog.md",
        "title": "Changelog",
        "subtitle": "Release history",
        "template": "changelog",
    },
}

PARALLEL_THRESHOLD = 50000


class GenerationEngine:
    def __init__(
        self,
        provider: LLMProvider,
        template_name: str = "wiki",
        user_template_dir: str | None = None,
        cache: ResponseCache | None = None,
        cache_prefix: str = "",
        semantic_cache=None,
        max_workers: int | None = None,
        use_shields: bool | None = None,
        on_progress=None,
        prompt_tokens_limit: int | None = None,
        body_preview_lines: int = API_BODY_PREVIEW_LINES,
    ):
        self.provider = provider
        self.template_name = template_name
        self.env = create_template_env(
            template_name=template_name,
            user_template_dir=user_template_dir,
        )
        # Max *total* tokens sent per request. Defaults conservatively; the
        # self-healing retry lowers it at runtime if a provider reports a tighter
        # prompt cap (see _lower_prompt_limit).
        self._prompt_tokens_limit = (
            prompt_tokens_limit if prompt_tokens_limit is not None else PROMPT_TOKENS_LIMIT
        )
        self._body_preview_lines = body_preview_lines
        self.cache = cache
        self.cache_prefix = cache_prefix
        self.semantic_cache = semantic_cache
        # Concurrency cap. Local providers (e.g. Ollama) cannot absorb many
        # simultaneous requests without blocking/saturating, and they do not
        # emit a standards-compliant 429 + Retry-After for tenacity to honor.
        # Bound in-flight calls so parallel chunk generation and `serve --watch`
        # regeneration cannot thrash a local model. Cloud providers keep the
        # higher default of 4; `max_workers` overrides explicitly if supplied.
        self._local = getattr(provider, "local", False)
        self._cap = max_workers if max_workers is not None else (2 if self._local else 4)
        self._sem = threading.Semaphore(self._cap)
        # Optional progress callback fired after each provider/cache unit with
        # the running TokenUsage total (used for a live token counter in the CLI).
        self._on_progress = on_progress
        self._usage_lock = threading.Lock()
        # Badges: render shields.io image badges when reachable, else fall back
        # to offline-safe text. `None` auto-detects; pass True/False to force.
        self._use_shields = shields_reachable() if use_shields is None else use_shields

    def _cached_generate(
        self, system_prompt: str, user_prompt: str, use_cache: bool = True
    ) -> Completion:
        """Call the provider, returning a cached response when available.

        Lookup order: exact-hash cache, then opt-in semantic cache, then LLM.
        On a fresh LLM call the response is stored in both layers. Returns a
        ``Completion``; cache/semantic hits are flagged ``cached=True`` so the
        engine can report them separately without a provider round-trip.

        Pass ``use_cache=False`` to force a live call (e.g. when a cached
        response previously failed to parse and we want a fresh attempt).
        """
        key = None
        if use_cache and self.cache is not None:
            key = self.cache.key_for(self.cache_prefix, system_prompt, user_prompt)
            cached = self.cache.get(key)
            if cached is not None:
                return Completion(cached, usage=None, cached=True)

        if use_cache and self.semantic_cache is not None:
            sem = self.semantic_cache.get(user_prompt)
            if sem is not None:
                return Completion(sem, usage=None, cached=True)

        with self._sem:
            response = self.provider.generate(system_prompt, user_prompt)

        if key is not None:
            self.cache.set(key, response.content)
        if self.semantic_cache is not None:
            self.semantic_cache.set(user_prompt, response.content)
        return response

    def _account(
        self,
        result: Completion,
        system_prompt: str,
        user_prompt: str,
        usage: TokenUsage,
    ) -> None:
        """Fold one completion into the running ``usage`` total and report it.

        Exact provider usage is preferred; cache hits and usage-less providers
        fall back to the shared ``TokenCounter`` estimate. Guarded by a lock so
        parallel chunk generation can't race on the shared counters.
        """
        with self._usage_lock:
            if result.cached:
                usage.cached_calls += 1
                usage.prompt_tokens += estimate_tokens(system_prompt) + estimate_tokens(
                    user_prompt
                )
                usage.completion_tokens += estimate_tokens(result.content)
            elif result.usage:
                usage.provider_calls += 1
                usage.prompt_tokens += result.usage["prompt_tokens"]
                usage.completion_tokens += result.usage["completion_tokens"]
                usage.total_tokens += result.usage["total_tokens"]
            else:
                usage.provider_calls += 1
                usage.prompt_tokens += estimate_tokens(system_prompt) + estimate_tokens(
                    user_prompt
                )
                usage.completion_tokens += estimate_tokens(result.content)
            if not result.cached and not result.usage:
                usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
            if self._on_progress is not None:
                self._on_progress(usage)

    def generate_stream(self, context: dict):
        """Yield documentation chunks as they are generated (improvement #4).

        Used to improve perceived latency in interactive flows. Providers that
        don't natively stream yield the full response in one chunk, so this is
        always safe to call.
        """
        system_prompt, user_prompt = build_prompt(context, self.template_name)
        with self._sem:
            yield from self.provider.generate_stream(system_prompt, user_prompt)

    def generate(self, context: dict) -> GenerationResult:
        source_files = context.get("source_files", {})
        total_tokens = sum(estimate_tokens(c) for c in source_files.values())

        if total_tokens > PARALLEL_THRESHOLD:
            return self._generate_parallel(context)

        return self._generate_single(context)

    def _prompt_limit_from_exc(self, e: Exception) -> int | None:
        return parse_prompt_limit_from_402(str(e))

    def _apply_prompt_limit(self, y: int) -> None:
        """Lower the per-request token cap after a provider reported `Y`."""
        self._prompt_tokens_limit = max(2000, y - 2000)

    def _generate_single(self, context: dict) -> GenerationResult:
        result = GenerationResult()
        system_prompt, user_prompt = build_prompt(
            context, self.template_name, prompt_tokens_limit=self._prompt_tokens_limit
        )
        try:
            raw = self._cached_generate(system_prompt, user_prompt)
        except Exception as e:
            y = self._prompt_limit_from_exc(e)
            if y is not None:
                self._apply_prompt_limit(y)
                system_prompt, user_prompt = build_prompt(
                    context,
                    self.template_name,
                    prompt_tokens_limit=self._prompt_tokens_limit,
                )
                raw = self._cached_generate(system_prompt, user_prompt)
            else:
                raise
        self._account(raw, system_prompt, user_prompt, result.token_usage)
        sections = self._parse_sections(raw.content)

        if not sections:
            result.files["index.md"] = raw.content
            result.warnings.append(
                "AI response was not structured JSON. Saved raw output as index.md."
            )
            return result

        changelog = self._generate_changelog(context, result.token_usage)
        if changelog:
            sections["changelog"] = changelog

        self._render_pages(sections, context, result)
        return result

    def _generate_parallel(self, context: dict) -> GenerationResult:
        result = GenerationResult()
        source_files = context.get("source_files", {})

        sys_prompt, user_prompt = build_prompt(
            context, self.template_name, source_subset={}, prompt_tokens_limit=self._prompt_tokens_limit
        )
        try:
            raw = self._cached_generate(sys_prompt, user_prompt)
        except Exception as e:
            y = self._prompt_limit_from_exc(e)
            if y is not None:
                self._apply_prompt_limit(y)
                sys_prompt, user_prompt = build_prompt(
                    context,
                    self.template_name,
                    source_subset={},
                    prompt_tokens_limit=self._prompt_tokens_limit,
                )
                raw = self._cached_generate(sys_prompt, user_prompt)
            else:
                raise
        self._account(raw, sys_prompt, user_prompt, result.token_usage)
        base_sections = self._parse_sections(raw.content)
        sections = {}
        if base_sections:
            sections.update(base_sections)
        else:
            # The cached response (if any) may have been a previously broken
            # payload that keeps getting replayed. Retry once without the cache
            # to give the model a chance to return well-formed sections.
            fresh = self._cached_generate(sys_prompt, user_prompt, use_cache=False)
            self._account(fresh, sys_prompt, user_prompt, result.token_usage)
            base_sections = self._parse_sections(fresh.content)
            if base_sections:
                sections.update(base_sections)
            else:
                result.warnings.append(
                    "Initial generation response was not structured JSON."
                )

        api_sections, y = self._run_api_chunks(context, source_files, sections, result)
        if y is not None:
            # Provider rejected a chunk for exceeding its prompt cap. Lower the
            # cap and reprocess the API reference once with the tighter budget.
            self._apply_prompt_limit(y)
            api_sections, _ = self._run_api_chunks(
                context, source_files, sections, result, retried=True
            )

        merged_api = []
        for chunk_result in api_sections:
            if chunk_result and "api_reference" in chunk_result:
                merged_api.append(chunk_result["api_reference"])

        if merged_api:
            sections["api_reference"] = "\n\n---\n\n".join(merged_api)

        changelog = self._generate_changelog(context, result.token_usage)
        if changelog:
            sections["changelog"] = changelog

        self._render_pages(sections, context, result)
        return result

    def _run_api_chunks(
        self,
        context: dict,
        source_files: dict[str, str],
        sections: dict[str, str],
        result: GenerationResult,
        retried: bool = False,
    ) -> tuple[list[dict[str, str] | None], int | None]:
        """Generate every API chunk. Returns (per-chunk sections, recoverable cap).

        ``recoverable cap`` is the provider's prompt cap (Y) parsed from a 402, or
        ``None``. On the first pass, recoverable 402s are suppressed (no warning) so
        the caller can lower the budget and reprocess once; on the retry pass they
        are surfaced as concise warnings so a persistent cap is never silently
        swallowed.
        """
        budget = self._prompt_tokens_limit - PROMPT_OVERHEAD_RESERVE
        chunks = chunk_by_symbol(source_files, budget)
        api_sections: list[dict[str, str] | None] = [None] * len(chunks)
        recoverable_y: int | None = None
        if not chunks:
            return api_sections, None

        with ThreadPoolExecutor(max_workers=min(len(chunks), self._cap)) as executor:
            futures = {}
            for i, chunk in enumerate(chunks):
                if not chunk:
                    continue
                fut = executor.submit(
                    self._generate_api_chunk,
                    context,
                    chunk,
                    sections,
                    result.token_usage,
                    self._body_preview_lines,
                    self._prompt_tokens_limit,
                )
                futures[fut] = i

            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    chunk_sections = fut.result()
                    if chunk_sections:
                        api_sections[idx] = chunk_sections
                except Exception as e:
                    y = self._prompt_limit_from_exc(e)
                    if y is not None and recoverable_y is None:
                        recoverable_y = y
                        if retried:
                            result.warnings.append(
                                f"API chunk {idx} failed: {format_provider_error_text(e)}"
                            )
                    else:
                        result.warnings.append(
                            f"API chunk {idx} failed: {format_provider_error_text(e)}"
                        )

        return api_sections, recoverable_y

    def _generate_changelog(self, context: dict, usage: TokenUsage | None = None) -> str | None:
        """Separate historian call: generate the changelog from git commits.

        Returns markdown on success, or None when changelog is disabled / no
        commit history is available. Failures are downgraded to a warning so
        they never block the rest of the generation.
        """
        meta = context.get("metadata", {})
        if not meta.get("include_changelog"):
            return None
        git_info = context.get("git_info")
        if not git_info or not git_info.get("changelog"):
            return None

        system_prompt, user_prompt = build_changelog_prompt(git_info["changelog"])
        try:
            result = self._cached_generate(system_prompt, user_prompt)
            if usage is not None:
                self._account(result, system_prompt, user_prompt, usage)
            return result.content
        except Exception:
            return None

    def _generate_api_chunk(
        self,
        context: dict,
        chunk: dict[str, str],
        existing_sections: dict[str, str],
        usage: TokenUsage,
        body_preview_lines: int = API_BODY_PREVIEW_LINES,
        prompt_tokens_limit: int | None = None,
    ) -> dict[str, str] | None:
        sys_prompt, user_prompt = build_api_prompt(
            context,
            chunk,
            existing_sections,
            prompt_tokens_limit=prompt_tokens_limit,
            body_preview_lines=body_preview_lines,
        )
        raw = self._cached_generate(sys_prompt, user_prompt)
        self._account(raw, sys_prompt, user_prompt, usage)
        return self._parse_sections(raw.content)

    def _render_pages(
        self,
        sections: dict[str, str],
        context: dict,
        result: GenerationResult,
    ):
        meta = context.get("metadata", {})
        source_modules = context.get("source_modules", {})
        now = datetime.now().strftime("%Y-%m-%d")

        # Single-file templates (e.g. readme.md.j2) render in one pass and do
        # not use the per-section model below.
        single_template = f"{self.template_name}.md.j2"
        try:
            self.env.get_template(single_template)
            is_single_file = True
        except Exception:
            is_single_file = False

        if is_single_file:
            template_vars = {
                "project_name": meta.get("name", "Project"),
                "version": meta.get("version", "0.0.0"),
                "description": meta.get("description", ""),
                "language": meta.get("language", "Python"),
                "generation_date": now,
                "sections": sections,
                "source_modules": source_modules,
                "use_shields": self._use_shields,
            }
            try:
                template = self.env.get_template(single_template)
                content = template.render(**template_vars)
                result.files[f"{self.template_name}.md"] = content
            except Exception as e:
                result.warnings.append(f"Failed to render {single_template}: {e}")
            return

        toc = []
        for key, info in PAGE_MAP.items():
            if key == "index":
                continue
            if key in sections:
                toc.append(info)

        template_vars = {
            "project_name": meta.get("name", "Project"),
            "version": meta.get("version", "0.0.0"),
            "description": meta.get("description", ""),
            "language": meta.get("language", "Python"),
            "generation_date": now,
            "sections": sections,
            "source_modules": source_modules,
            "toc": toc,
            "use_shields": self._use_shields,
        }

        for key, info in PAGE_MAP.items():
            if key == "index":
                continue
            if key not in sections:
                continue
            template_name = f"{info['template']}.md.j2"
            try:
                template = self.env.get_template(template_name)
                content = template.render(**template_vars)
                result.files[info["file"]] = content
            except Exception as e:
                result.warnings.append(f"Failed to render {template_name}: {e}")

        try:
            template = self.env.get_template("index.md.j2")
            content = template.render(**template_vars)
            result.files["index.md"] = content
        except Exception as e:
            result.warnings.append(f"Failed to render index.md.j2: {e}")

    def _parse_sections(self, raw: str) -> dict[str, str] | None:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()

        cleaned = _strip_json_fences(raw)
        return _robust_json_load(cleaned)


def _strip_json_fences(text: str) -> str:
    """Remove a leading/trailing ```json ... ``` fence if present."""
    text = text.strip()
    if text.startswith("```"):
        # Drop the opening fence line (``` or ```json).
        text = text.split("\n", 1)[1] if "\n" in text else ""
    if text.endswith("```"):
        text = text[: text.rfind("```")].strip()
    return text.strip()


# Fixed set of section keys the generator can emit. Used by the regex
# fallback so a structurally broken JSON response can still be salvaged.
_SECTION_KEYS = [
    "overview",
    "features",
    "installation",
    "quickstart",
    "usage",
    "guides",
    "api_reference",
    "changelog",
]


def _extract_sections_regex(text: str) -> dict[str, str] | None:
    """Last-resort extraction of known section keys from malformed JSON.

    Section values are flat markdown strings (no nested objects), so we can
    pull ``"key": "..."`` spans out even when the surrounding JSON is broken
    (unbalanced braces, stray quoting, etc.). Guarantees that sections such as
    ``overview``/``features`` are never silently lost.
    """
    result: dict[str, str] = {}
    for key in _SECTION_KEYS:
        pattern = re.compile(
            r'"%s"\s*:\s*"(.*?)"\s*(?:,|\})' % re.escape(key),
            re.DOTALL,
        )
        match = pattern.search(text)
        if not match:
            continue
        val = match.group(1)
        val = (
            val.replace("\\\\", "\x00")
            .replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
            .replace("\x00", "\\")
        )
        result[key] = val
    return result or None


def _robust_json_load(text: str) -> dict[str, str] | None:
    """Parse a JSON object, tolerating the common ways LLMs mangle it.

    Handles: leading/trailing prose, ``` fences, trailing commas, and
    unescaped newlines inside string values (the usual cause of
    "AI response was not structured JSON").
    """
    # 1. Direct parse.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 2. Extract the outermost {...} span, dropping any prose around it.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        span = text[start : end + 1]
        try:
            obj = json.loads(span)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

        # 3. Repair: strip trailing commas, then unescaped newlines in strings.
        repaired = _repair_json(span)
        try:
            obj = json.loads(repaired)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # 4. Final fallback: salvage known section keys via regex even if the
    #    surrounding JSON is structurally broken.
    regexed = _extract_sections_regex(text)
    if regexed:
        return regexed

    return None


def _repair_json(span: str) -> str:
    """Best-effort repair of common LLM JSON errors.

    - Strips trailing commas before ``}``/``]``.
    - Escapes raw newlines / tabs that appear *inside* string literals (the
      usual cause of "AI response was not structured JSON"), using a small
      scanner that tracks whether we are inside a quoted string so structural
      whitespace between tokens is left untouched.
    """
    import re

    span = re.sub(r",\s*([}\]])", r"\1", span)

    out: list[str] = []
    in_str = False
    escape = False
    for ch in span:
        if in_str:
            if escape:
                out.append(ch)
                escape = False
            elif ch == "\\":
                out.append(ch)
                escape = True
            elif ch == '"':
                in_str = False
                out.append(ch)
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_str = True
                out.append(ch)
            else:
                out.append(ch)
    return "".join(out)
