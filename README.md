<div align="center" markdown="1">

# DocGen

**AI-powered documentation generator for solo/indie developers.**

[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](https://github.com/khrlagst/docgen)
[![Language](https://img.shields.io/badge/language-Python-green.svg)](https://github.com/khrlagst/docgen)
[![Generated](https://img.shields.io/badge/generated-docgen-8A2BE2)](https://github.com/khrlagst/docgen)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

Docgen helps you turn source code, project metadata, and optional Git context into polished documentation with a simple CLI workflow.

## Features

- Generate documentation from a codebase with AI
- Scaffold a documentation project with `docgen init`
- Refine existing markdown sections with `docgen refine`
- Preview, export, and build site outputs
- Run an interactive terminal UI by launching `docgen` with no arguments

## Installation

Install from the local checkout:

```bash
pip install -e .
```

Or install the test extras if you want to run the test suite:

```bash
pip install -e ".[test]"
```

## Quick start

1. Initialize a documentation project:

```bash
docgen init .
```

2. Generate documentation from your source tree:

```bash
docgen generate --source src --template wiki
```

3. Preview the generated docs locally:

```bash
docgen serve
```

## CLI usage

### `docgen init`

Scaffold a new documentation project and create a `docs/` directory.

```bash
docgen init .
```

Optional flags:

```bash
docgen init . --force
```

### `docgen generate`

Generate documentation from your project source.

```bash
docgen generate --source src --template wiki --output docs
```

Common options:

- `--source`, `-s`: source directory to analyze
- `--template`, `-t`: template style (`wiki`, `manual`, or `readme`)
- `--output`, `-o`: output directory for generated files

### `docgen refine`

Improve an existing markdown file with AI guidance.

```bash
docgen refine docs/index.md --prompt "Add more examples"
```

### `docgen serve`

Preview generated documentation locally.

```bash
docgen serve --port 8080 --watch
```

### `docgen export`

Export markdown docs to PDF.

```bash
docgen export docs docs.pdf
```

### `docgen config`

Inspect or configure project settings.

```bash
docgen config show
docgen config set llm.api_key YOUR_KEY
```

Unknown keys print a hint suggesting the closest known key (e.g.
`llm.apikeey` → `llm.api_key`), so typos are easy to catch.

### `docgen html`

Export the generated docs as a single self-contained HTML file (embedded CSS,
no external dependencies).

```bash
docgen html docs docs.html
```

### `docgen site`

Generate an `mkdocs.yml` (Material theme) from the generated docs so you can
run `mkdocs serve` / `mkdocs build` to publish a static site.

```bash
docgen site docs _site
```

### `docgen models` / `docgen providers`

List the model IDs Docgen knows per provider, or list the supported providers.

```bash
docgen providers
docgen models --provider gemini
docgen models --refresh   # fetch live model lists (needs API key / local server)
```

Docgen supports 10 providers out of the box: OpenAI, Anthropic, Google Gemini,
Groq, Mistral, Together, Azure OpenAI, DeepSeek, OpenRouter, and local Ollama.

## Configuration & privacy

- **Per-project config:** When you run a command inside a project, Docgen reads
  `<project>/.docgen/config.toml` (project-local) overlaid on the global
  `~/.config/docgen/config.toml`. `docgen init` writes the project config to
  `.docgen/`, and `docgen config set` writes to the project-local file.
- **Secrets stay out of version control:** both `docgen init` and `docgen config set`
  append `.docgen/` to the project's `.gitignore` (creating it if needed), so a
  project-local API key is never committed — even if you set a key *before*
  running `init`.
- **Respects `.gitignore`:** Source scanning (`read_source_files`,
  `build_project_tree`, `parse_project`, `summarize_workflows`) skips paths
  excluded by your `.gitignore` as well as common build artifacts
  (`node_modules/`, `dist/`, `__pycache__/`, …), and stops once a token budget
  is reached instead of blindly capping file count.
- **Rate-limit backoff:** All providers retry transient errors
  (`RateLimitError`, timeouts, connection errors) with exponential backoff +
  jitter, honoring a `Retry-After` header when the provider sends one.
  Auth/4xx errors surface immediately with a friendly message.
- **Local-only preview:** `docgen serve` binds to `127.0.0.1` (loopback) only,
  so the preview server is never exposed to your local network.
- **Hermetic PDF export:** WeasyPrint rendering blocks all remote resource
  fetches (images, CSS), so exporting docs never leaks data or makes outbound
  network requests.

## Smart context handling

- **Token counting:** `docgen/generator/tokens.py` provides a `TokenCounter`
  (tiktoken `cl100k_base` with a char/4 fallback) for accurate pre-flight
  estimates.
- **Skeleton extraction:** oversized Python files (>4k tokens) are sent to the
  model as a *skeleton* — signatures, decorators, and docstrings only, with
  function/method bodies stripped. This cuts token cost and keeps internal
  implementation logic on your machine (security best practice).
- **Manifest detection:** Docgen reads `package.json`, `pyproject.toml`,
  `Cargo.toml`, or `go.mod` to detect the language, version (Node/Python/Rust/Go),
  and frameworks (React, Vue, Next.js, FastAPI, Django, …), and feeds that
  context to the model so it uses the correct terminology.
- **Three focused prompts:** documentation is generated by three separate
  prompts — the *architect* (overview/guides/API), the *inspector* (API
  reference), and the *historian* (changelog from git commits) — each a small,
  cache-friendly unit of work.

## Live preview & caching

- **Source-watch preview:** `docgen serve --watch` starts a local docs
  preview and watches your **source** tree with `watchdog`. Editing a source
  file regenerates the docs in place (the server reads files fresh on each
  request, so just refresh the browser — no restart). The pipeline reuses the
  exact-hash cache, so only the changed file's pages are actually re-sent to
  the model. Pass `--source`/`-s` and `--template`/`-t` to control what is
  watched and which template is used.
- **Exact-hash cache (default):** prompts are keyed by provider/model + full
  prompt, so re-runs on unchanged code cost **zero** tokens.
- **Semantic cache (opt-in):** enable with `generation.semantic_cache = true`
  in config (or `--semantic-cache` on `generate`). It adds an offline
  bag-of-words similarity layer so *near-duplicate* prompts — e.g. a trivial
  whitespace/punctuation edit — hit the cache without a model call. Off by
  default; `chromadb` is available as the optional `semantic` extra for
  embedding-based matching.
- **Streaming (perceived latency):** `generate_stream()` is wired to the
  providers' streaming path (the base provider yields the full response as one
  chunk, so it always degrades gracefully).

## Interactive TUI

Run the interactive experience with no command:

```bash
docgen
```

This launches a terminal UI with command suggestions and a simple banner.

## Development

Run the tests:

```bash
pytest -q
```

## Notes

Docgen expects project metadata and, for generation, an LLM configuration such as an API key. If you have not configured one yet, the generate flow will prompt you to set it up before continuing.
