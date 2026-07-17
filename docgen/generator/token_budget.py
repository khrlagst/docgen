from __future__ import annotations

import ast
import re

MAX_PROMPT_TOKENS = 96000
# Default cap on the *total* tokens we send per request. The OpenRouter/DeepSeek
# keys commonly cap prompts well below the model context window (e.g. 25,578), so
# we default conservatively and let the self-healing retry lower it further if a
# provider reports a tighter cap.
PROMPT_TOKENS_LIMIT = 20000
# Reserve for the static instructions/system prompt so the *source* budget stays
# under the provider's prompt cap.
PROMPT_OVERHEAD_RESERVE = 2000
CHARS_PER_TOKEN = 4

# Per-file token threshold above which a Python file is sent as a skeleton
# (signatures + docstrings only) instead of its full body, to cut token cost
# and avoid shipping internal logic to the provider (security-and-hardening LLM02).
SKELETON_TOKEN_THRESHOLD = 4000

# Number of body lines kept after each signature/docstring for the API-reference
# prompt, so undocumented functions still get a real description without shipping
# the full private implementation.
API_BODY_PREVIEW_LINES = 15


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def maybe_skeleton(path: str, content: str, body_preview_lines: int = 0) -> tuple[str, bool]:
    """Return ``(content, is_skeleton)``.

    Oversized Python files are reduced to a skeleton (bodies stripped, or a short
    body preview when ``body_preview_lines > 0``); other files are returned
    unchanged. This is the routing half of #5/#8.
    """
    if not path.endswith(".py"):
        return content, False
    from docgen.generator.tokens import default_counter

    if default_counter().count(content) <= SKELETON_TOKEN_THRESHOLD:
        return content, False
    from docgen.context.source import extract_skeleton

    return extract_skeleton(content, body_preview_lines), True


def truncate_source_files(
    source_files: dict[str, str], max_tokens: int = MAX_PROMPT_TOKENS
) -> dict[str, str]:
    total = sum(estimate_tokens(c) for c in source_files.values())
    if total <= max_tokens:
        return source_files

    result = {}
    budget = max_tokens
    for path, content in source_files.items():
        tokens = estimate_tokens(content)
        if tokens <= budget:
            result[path] = content
            budget -= tokens
        else:
            truncated = content[: budget * CHARS_PER_TOKEN]
            result[path] = truncated + "\n# ... [truncated]"
            break
    return result


def chunk_source_files(
    source_files: dict[str, str], max_tokens: int = MAX_PROMPT_TOKENS
) -> list[dict[str, str]]:
    """Split source files into chunks that each fit within max_tokens."""
    total = sum(estimate_tokens(c) for c in source_files.values())
    if total <= max_tokens:
        return [source_files]

    chunks = []
    current: dict[str, str] = {}
    current_tokens = 0

    for path, content in source_files.items():
        tokens = estimate_tokens(content)
        if current_tokens + tokens > max_tokens and current:
            chunks.append(current)
            current = {}
            current_tokens = 0

        if tokens > max_tokens:
            truncated = content[: max_tokens * CHARS_PER_TOKEN]
            truncated += "\n# ... [truncated]"
            chunks.append({path: truncated})
        else:
            current[path] = content
            current_tokens += tokens

    if current:
        chunks.append(current)

    return chunks


_TOP_LEVEL_DEF_RE = re.compile(
    r"^(?:export\s+|public\s+|private\s+|protected\s+|async\s+|static\s+|def\s+)?"
    r"(?:def|class|function|func|interface|struct|impl|module|const|let|var|fn|sub|pub)\b"
)


def _symbol_spans(content: str, path: str) -> list[str]:
    """Split a file's source into top-level symbol spans.

    Python uses the AST for precise spans; other languages use a heuristic that
    cuts at column-0 definition keywords. Falls back to the whole file when no
    symbols are detected.
    """
    if path.endswith(".py"):
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return [content]
        spans = [
            seg
            for node in tree.body
            if (seg := ast.get_source_segment(content, node))
        ]
        return spans or [content]

    lines = content.splitlines()
    spans: list[str] = []
    current: list[str] = []
    for line in lines:
        if current and not line.startswith((" ", "\t")) and _TOP_LEVEL_DEF_RE.match(line):
            spans.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        spans.append("\n".join(current))
    return spans or [content]


def chunk_by_symbol(
    source_files: dict[str, str], max_tokens: int = MAX_PROMPT_TOKENS
) -> list[dict[str, str]]:
    """Split source files into chunks that each fit within ``max_tokens``.

    Unlike ``chunk_source_files``, chunks are bounded at **top-level symbol
    boundaries** (via ``_symbol_spans``) so a single function/class is never cut
    in half — every symbol is sent complete. Symbols are packed across files up to
    the budget (accounting for inter-symbol separators); a symbol larger than
    ``max_tokens`` is truncated to fit, leaving room for the truncation marker.
    """
    file_symbols = {
        path: _symbol_spans(content, path) for path, content in source_files.items()
    }

    SEP = 2  # tokens consumed by the "\n\n" joining symbols
    chunks: list[dict[str, str]] = []
    current: dict[str, list[str]] = {}
    current_est = 0

    for path, spans in file_symbols.items():
        for span in spans:
            tokens = estimate_tokens(span)
            if tokens > max_tokens:
                room = max(0, (max_tokens - 4) * CHARS_PER_TOKEN)
                span = span[:room] + "\n# ... [truncated]"
                tokens = estimate_tokens(span)
            sep = SEP if current_est else 0
            if current_est + sep + tokens > max_tokens and current:
                chunks.append(current)
                current = {}
                current_est = 0
                sep = 0
            current.setdefault(path, []).append(span)
            current_est += tokens + (SEP if current_est else 0)

    if current:
        chunks.append(current)

    return [{p: "\n\n".join(s) for p, s in current.items()} for current in chunks]

