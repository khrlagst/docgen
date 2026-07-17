import json

from docgen.generator.token_budget import (
    maybe_skeleton,
    truncate_source_files,
    PROMPT_TOKENS_LIMIT,
    PROMPT_OVERHEAD_RESERVE,
    API_BODY_PREVIEW_LINES,
)

SYSTEM_PROMPT = """You are a senior technical documentation writer. Your expertise is reading source code and producing accurate, insightful documentation that captures what a project actually does.

## Your Process
1. **Read all source code provided** — analyze the implementation, not just comments
2. **Understand the architecture** — how files connect, what patterns are used
3. **Identify the core purpose** — what problem does this project solve
4. **Generate documentation** that reflects genuine understanding

## Output Rules
- Write in a professional, neutral tone
- Be specific and concrete — reference actual types, functions, and patterns from the code
- Always include real usage examples derived from the code
- When describing functions/classes, cover: purpose, parameters, return values, and examples
- If the code lacks something, say "[Not implemented]" rather than inventing
- When documenting usage, installation, or quickstart, reference ONLY the commands, flags, and Python API listed in the provided "CLI / API Surface" section. Never invent CLI subcommands, flags, or Python functions.
- Use rich markdown formatting: **bold**, `code`, ```code blocks```, tables, lists, blockquotes
- When listing items, always use a markdown bullet list with each `- ` item on its **own line** — never write an inline run like `Text: - item A - item B - item C`. Start every list item on a fresh line.

## Quality Standards
- Do NOT write generic documentation that could apply to any project
- Every statement should be traceable to actual code
- If the project has a specific domain (finance, gaming, API, etc.), use the correct terminology

## Formatting Style
- Use emoji prefixes for section headings where appropriate: 🚀 Quick Start, 📦 Installation, 📚 API
- Use `>` blockquotes for notes and callouts
- Use tables with aligned columns for structured data
- Use ``` with language tags for code blocks
- Use **bold** for UI elements and important terms
- Keep paragraphs short and scannable
"""


def build_source_section(source_files: dict[str, str], body_preview_lines: int = 0) -> str:
    if not source_files:
        return ""

    section = "## Source Code\n\nBelow is the source code of the project. Read it carefully before generating documentation.\n\n"
    section += "```\nProject file structure:\n"
    for path in source_files:
        section += f"  {path}\n"
    section += "```\n\n"

    for path, content in source_files.items():
        routed, is_skeleton = maybe_skeleton(path, content, body_preview_lines)
        if body_preview_lines and is_skeleton:
            label = " (skeleton — signatures, docstrings, and a body preview)"
        elif is_skeleton:
            label = " (skeleton — signatures and docstrings only)"
        else:
            label = ""
        section += f"### File: `{path}`{label}\n\n"
        section += f"```\n{routed}\n```\n\n"

    return section


def _build_section_list(meta: dict) -> list[tuple[str, str]]:
    sections = [
        ("overview", "Project overview — what it does, who it's for, core architecture"),
        ("features", "Key features derived from the code"),
        ("installation", "Step-by-step installation instructions"),
        ("quickstart", "Quick start guide with a concrete working example"),
        ("usage", "Detailed usage guide referencing actual classes/functions from the code — use ONLY the commands/API listed in the CLI/API Surface section; never invent subcommands, flags, or functions."),
    ]

    if meta.get("include_api"):
        sections.append(("api_reference", "Complete API reference covering all public functions, classes, methods with signatures, descriptions, parameters, return types, and examples from the code"))

    if meta.get("include_guides"):
        sections.append(("guides", "User guides and tutorials"))

    return sections


def build_prompt(
    context: dict,
    template_name: str = "wiki",
    source_subset: dict[str, str] | None = None,
    prompt_tokens_limit: int | None = None,
) -> tuple[str, str]:
    meta = context.get("metadata", {})

    sections = _build_section_list(meta)
    keys_spec = "\n".join(
        f'  "{key}": "{desc}"' for key, desc in sections
    )

    source_files = source_subset if source_subset is not None else context.get("source_files", {})
    budget = (prompt_tokens_limit or PROMPT_TOKENS_LIMIT) - PROMPT_OVERHEAD_RESERVE
    source_files = truncate_source_files(source_files, max_tokens=budget)
    source_section = build_source_section(source_files)

    project_tree = context.get("project_tree")
    workflow_summary = context.get("workflow_summary")
    tree_section = ""
    if project_tree:
        tree_section = f"## Project Tree\n\n{project_tree}\n\n"

    workflow_section = ""
    if workflow_summary:
        workflow_section = f"## Workflows\n\n{workflow_summary}\n\n"

    cli_surface = context.get("cli_surface")
    cli_section = ""
    if cli_surface:
        cli_section = (
            "## CLI / API Surface (GROUND TRUTH — use ONLY these for usage/quickstart)\n\n"
            f"{cli_surface}\n\n"
        )

    stack_section = ""
    stack = meta.get("stack")
    if stack:
        stack_section = "## Detected Tech Stack\n\n"
        stack_section += f"- Language: {stack.get('language', meta.get('language', 'Unknown'))}\n"
        for key, value in (stack.get("versions") or {}).items():
            stack_section += f"- {key}: {value}\n"
        frameworks = stack.get("frameworks") or []
        if frameworks:
            stack_section += f"- Frameworks: {', '.join(frameworks)}\n"
        stack_section += "\n"

    user_prompt = f"""Analyze the following project and generate comprehensive documentation.

## Project Metadata
- Name: {meta.get('name', 'Unknown')}
- Version: {meta.get('version', '0.0.0')}
- Description: {meta.get('description', '')}
- Language: {meta.get('language', 'Unknown')}

    {stack_section}{tree_section}{workflow_section}{cli_section}{source_section}

## Task

Read every source file above. Understand what this project actually does. Then generate documentation.

Return a JSON object with these exact keys. Each value is markdown-formatted content for that section.

The keys:
{keys_spec}

IMPORTANT: Return ONLY valid JSON. No markdown code fences around it. No extra text before or after.
"""

    return SYSTEM_PROMPT, user_prompt


def build_api_prompt(
    context: dict,
    source_subset: dict[str, str],
    existing_sections: dict[str, str] | None = None,
    prompt_tokens_limit: int | None = None,
    body_preview_lines: int = API_BODY_PREVIEW_LINES,
) -> tuple[str, str]:
    """Build a prompt focused only on API reference for a subset of source files."""
    meta = context.get("metadata", {})

    budget = (prompt_tokens_limit or PROMPT_TOKENS_LIMIT) - PROMPT_OVERHEAD_RESERVE
    source_subset = truncate_source_files(source_subset, max_tokens=budget)
    source_section = build_source_section(source_subset, body_preview_lines)

    context_sections = {
        k: v for k, v in (existing_sections or {}).items() if k != "api_reference"
    }
    context_str = json.dumps(context_sections, indent=2)[:1200]

    api_prompt = f"""You are generating API documentation for part of a project.

## Project
- Name: {meta.get('name', 'Unknown')}
- Language: {meta.get('language', 'Unknown')}

## Source Files
{source_section}

## Existing Sections (context only — do NOT regenerate these)
{context_str}

## Task
Generate ONLY the API reference section for the source files above.
Document every public function, class, method with signatures, parameters, return values, and examples.

Return a JSON object with exactly one key:
  "api_reference": "Complete API markdown content for these files"

IMPORTANT: Return ONLY valid JSON. No markdown code fences around it. No extra text before or after.
"""
    return (
        "You are a technical documentation writer specializing in API documentation. Be precise and thorough.",
        api_prompt,
    )


def build_changelog_prompt(commits: list[dict]) -> tuple[str, str]:
    """Build a focused prompt for the *historian* role: turn git commits into a changelog.

    Kept separate from the architect (`build_prompt`) and inspector
    (`build_api_prompt`) calls so the changelog is its own cheap, cache-friendly
    unit of work (context-engineering: selective include).
    """
    system = (
        "You are a meticulous release historian. You convert raw git commit "
        "logs into a clean, human-readable changelog. Be accurate: never invent "
        "commits that are not in the list."
    )

    if not commits:
        return system, (
            "No commit history is available. Return a single sentence stating "
            "that a changelog could not be generated from version control."
        )

    lines = []
    for c in commits[:50]:
        sha = str(c.get("sha", ""))[:7]
        msg = " ".join(str(c.get("message", "")).split())
        author = c.get("author", "")
        date = c.get("date", "")
        lines.append(f"- {sha} {msg} ({author}, {date})")

    user = f"""Below are the most recent commits for this project.

## Commits
{chr(10).join(lines)}

## Task
Write a CHANGELOG in Markdown. Group changes logically (Added / Changed / Fixed)
where the messages allow, use version headings where tags are evident, and keep
entries concise. Return ONLY the markdown changelog — no code fences, no extra prose.
"""
    return system, user
