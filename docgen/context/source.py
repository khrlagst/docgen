import ast
from pathlib import Path

from docgen.context.gitignore import is_ignored, load_gitignore_spec


class SourceParser(ast.NodeVisitor):
    def __init__(self, source: str):
        self.source = source
        self._lines = source.splitlines()
        self.tree = ast.parse(source)
        self.functions = []
        self.classes = []

    def _seg(self, node) -> str:
        """Source text for ``node`` via line/col offsets — O(span), not O(source).

        ``ast.get_source_segment`` re-scans the whole source per call, which is
        O(n) per node and O(n**2) for a file with many functions. Slicing the
        pre-split lines by ``lineno``/``col_offset`` keeps skeleton building linear.
        """
        sl = self._lines
        start = node.lineno - 1
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        col = getattr(node, "col_offset", 0)
        end_col = getattr(node, "end_col_offset", None)
        if start == end - 1:
            line = sl[start]
            return line[col:end_col] if end_col is not None else line[col:]
        first = sl[start][col:]
        middle = sl[start + 1 : end - 1]
        last = sl[end - 1][:end_col] if end_col is not None else sl[end - 1]
        return "\n".join([first, *middle, last])

    def parse(self) -> dict:
        self.visit(self.tree)
        return {
            "module_docstring": ast.get_docstring(self.tree),
            "functions": self.functions,
            "classes": self.classes,
        }

    def visit_FunctionDef(self, node):
        self.functions.append({
            "name": node.name,
            "lineno": node.lineno,
            "docstring": ast.get_docstring(node),
            "args": [a.arg for a in node.args.args],
            "returns": (
                ast.get_source_segment(self.source, node.returns)
                if node.returns
                else None
            ),
            "decorators": [
                ast.get_source_segment(self.source, d)
                for d in node.decorator_list
            ],
        })
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node):
        methods = [
            {"name": n.name, "docstring": ast.get_docstring(n)}
            for n in node.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.classes.append({
            "name": node.name,
            "docstring": ast.get_docstring(node),
            "methods": methods,
            "bases": [
                ast.get_source_segment(self.source, b)
                for b in node.bases
            ],
        })
        self.generic_visit(node)

    def skeleton(self, body_preview_lines: int = 0) -> str:
        """Return signatures + docstrings with function/method bodies stripped.

        Sends far fewer tokens to the provider than full source and, per
        security-and-hardening (LLM02), keeps internal implementation logic on
        the local machine. Only used for oversized Python files.

        When ``body_preview_lines > 0`` (the API-reference path), the first N
        non-empty lines of each function body are kept after the docstring so the
        model can infer behavior without shipping the full private implementation.
        """
        lines: list[str] = []
        module_doc = ast.get_docstring(self.tree)
        if module_doc:
            lines.append(f'"""{module_doc}"""')
        for node in self.tree.body:
            lines.append(self._skeleton_node(node, 0, body_preview_lines))
        return "\n".join(lines)

    def _skeleton_node(self, node, indent: int, body_preview_lines: int = 0) -> str:
        pad = "    " * indent
        # Docstring expression nodes are rendered via get_docstring elsewhere;
        # skip them so they don't appear as "# Expr".
        if isinstance(node, ast.Expr) and isinstance(
            getattr(node, "value", None), ast.Constant
        ):
            if isinstance(node.value.value, str):
                return ""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = ", ".join(a.arg for a in node.args.args)
            ret = (
                f" -> {self._seg(node.returns)}"
                if node.returns
                else ""
            )
            decs = "".join(
                f"@{self._seg(d)}\n{pad}"
                for d in node.decorator_list
            )
            doc = ast.get_docstring(node)
            header = f"{pad}{decs}def {node.name}({args}){ret}:"
            if not doc and not body_preview_lines:
                return header
            out = [header]
            if doc:
                out.append(f'{pad}    """{doc}"""')
            if body_preview_lines and node.body:
                src = self._seg(node)
                src_lines = src.splitlines()
                start = 1
                if doc:
                    first = node.body[0]
                    start = first.end_lineno - node.lineno + 1
                for pl in src_lines[start : start + body_preview_lines]:
                    if pl.strip():
                        out.append(pl)
            return "\n".join(out)
        if isinstance(node, ast.ClassDef):
            bases = ", ".join(
                ast.get_source_segment(self.source, b) for b in node.bases
            )
            header = f"{pad}class {node.name}" + (f"({bases})" if bases else "") + ":"
            out = [header]
            doc = ast.get_docstring(node)
            if doc:
                out.append(f'{pad}    """{doc}"""')
            for child in node.body:
                rendered = self._skeleton_node(child, indent + 1, body_preview_lines)
                if rendered:
                    out.append(rendered)
            return "\n".join(out)
        if isinstance(node, ast.Import):
            return f"{pad}import ..."
        if isinstance(node, ast.ImportFrom):
            return f"{pad}from ... import ..."
        return f"{pad}# {type(node).__name__}"


def extract_skeleton(content: str, body_preview_lines: int = 0) -> str:
    """Best-effort Python skeleton; falls back to the original source on error.

    ``body_preview_lines`` forwards to ``SourceParser.skeleton`` (see there).
    """
    try:
        return SourceParser(content).skeleton(body_preview_lines)
    except SyntaxError:
        return content


def parse_project(src_dir: Path) -> dict:
    from docgen.context.parsers import parse_source_file

    src_dir = Path(src_dir)
    spec = load_gitignore_spec(src_dir)
    modules = {}
    for ext in SOURCE_EXTENSIONS:
        for f in sorted(src_dir.rglob(f"*{ext}")):
            rel_parts = f.relative_to(src_dir).parts
            if any(p.startswith(".") for p in rel_parts):
                continue
            if is_ignored(f, src_dir, spec):
                continue
            try:
                source = f.read_text(encoding="utf-8")
                rel = str(f.relative_to(src_dir))
                if ext == ".py":
                    parser = SourceParser(source)
                    modules[rel] = parser.parse()
                else:
                    modules[rel] = parse_source_file(f, source)
            except (SyntaxError, Exception):
                continue
    return modules


SOURCE_EXTENSIONS = [
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".go", ".rs", ".java", ".kt", ".swift",
    ".rb", ".php", ".c", ".cpp", ".h", ".hpp",
    ".html", ".css", ".scss", ".less",
    ".sql", ".r", ".m",
]


def read_source_files(
    src_dir: Path,
    token_budget: int = 200_000,
    max_files: int | None = None,
) -> dict[str, str]:
    """Read full source file contents for AI analysis.

    Skips paths excluded by the project .gitignore (see `gitignore.py`) and
    stops once a token budget is reached instead of silently capping at a fixed
    file count. `max_files` (if set) is an additional hard ceiling.
    """
    src_dir = Path(src_dir)
    spec = load_gitignore_spec(src_dir)
    files: dict[str, str] = {}
    used = 0
    for ext in SOURCE_EXTENSIONS:
        for f in sorted(src_dir.rglob(f"*{ext}")):
            rel_parts = f.relative_to(src_dir).parts
            if any(p.startswith(".") for p in rel_parts):
                continue
            if is_ignored(f, src_dir, spec):
                continue
            if max_files is not None and len(files) >= max_files:
                return files
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                continue
            used += estimate_tokens(content)
            files[str(f.relative_to(src_dir))] = content
            if used >= token_budget:
                return files
    return files


EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".jsx": "JavaScript (React)",
    ".tsx": "TypeScript (React)",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".sql": "SQL",
    ".r": "R",
    ".m": "Objective-C",
}


def detect_language(src_dir: Path, source_files: dict[str, str]) -> str:
    """Detect the primary language of a project from its source files."""
    counts: dict[str, int] = {}
    for path in source_files:
        ext = Path(path).suffix
        lang = EXTENSION_LANGUAGE_MAP.get(ext)
        if lang:
            counts[lang] = counts.get(lang, 0) + len(source_files[path])

    if not counts:
        return "Unknown"

    return max(counts, key=counts.get)


def build_project_tree(src_dir: Path, max_entries: int = 80) -> str:
    """Build a compact tree view of the *source* files in the project.

    Only source files (matching ``SOURCE_EXTENSIONS``) are listed, so generated
    output such as a ``docs/`` directory living inside the source tree is excluded.
    This keeps the tree stable across re-runs and, importantly, stops generated
    docs from changing the prompt hash that the response cache keys on.
    """
    src_dir = Path(src_dir)
    spec = load_gitignore_spec(src_dir)
    entries: list[str] = []
    for ext in SOURCE_EXTENSIONS:
        for path in sorted(src_dir.rglob(f"*{ext}")):
            rel = path.relative_to(src_dir)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if is_ignored(path, src_dir, spec):
                continue
            if len(entries) >= max_entries:
                break
            entries.append(rel.as_posix())
        if len(entries) >= max_entries:
            break

    if not entries:
        return "(no source files found)"

    return "\n".join(entries)


def summarize_workflows(src_dir: Path, max_items: int = 8) -> str:
    """Create a lightweight workflow summary from likely entry points and CLI scripts.

    Only source files are considered (matching ``read_source_files``) so generated
    output under the source tree doesn't leak into the prompt.
    """
    src_dir = Path(src_dir)
    spec = load_gitignore_spec(src_dir)
    candidates = []
    for ext in SOURCE_EXTENSIONS:
        for path in sorted(src_dir.rglob(f"*{ext}")):
            rel = path.relative_to(src_dir)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if is_ignored(path, src_dir, spec):
                continue
            lower = rel.as_posix().lower()
            if any(token in lower for token in ["cli", "main", "app", "server", "workflow", "run"]):
                candidates.append(rel)

    if not candidates:
        return "- No explicit workflow entry points detected."

    summary = []
    for rel in candidates[:max_items]:
        summary.append(f"- {rel}")
    return "\n".join(summary)


def estimate_tokens(text: str) -> int:
    return len(text) // 4
