import re
from pathlib import Path


class BaseParser:
    ext: str = ""
    language: str = ""

    def parse(self, source: str) -> dict:
        return {
            "module_docstring": self._extract_module_doc(source),
            "functions": self._extract_functions(source),
            "classes": self._extract_classes(source),
        }

    def _extract_module_doc(self, source: str) -> str | None:
        return None

    def _extract_functions(self, source: str) -> list[dict]:
        return []

    def _extract_classes(self, source: str) -> list[dict]:
        return []


class JsTsParser(BaseParser):
    ext = ".js,.ts,.jsx,.tsx"
    language = "JavaScript/TypeScript"

    COMMENT_RE = re.compile(r"/\*\*([^*]|\*[^/])*\*/")
    FUNC_RE = re.compile(
        r"(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)\s*\{"
    )
    ARROW_FUNC_RE = re.compile(
        r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*(?:=>|->)"
    )
    METHOD_RE = re.compile(
        r"(\w+)\s*\(([^)]*)\)\s*\{"
    )
    CLASS_RE = re.compile(
        r"class\s+(\w+)(?:\s+extends\s+(\w+))?\s*\{"
    )
    CTOR_RE = re.compile(
        r"constructor\s*\(([^)]*)\)\s*\{"
    )

    def _extract_module_doc(self, source: str) -> str | None:
        match = self.COMMENT_RE.search(source[:2000])
        if match:
            text = match.group()
            lines = [l.strip().lstrip("*").strip() for l in text.split("\n")]
            body = [l for l in lines if l and not l.startswith("/")]
            return " ".join(body) if body else None
        return None

    def _extract_functions(self, source: str) -> list[dict]:
        functions = []
        seen = set()

        for regex in [self.FUNC_RE, self.ARROW_FUNC_RE]:
            for match in regex.finditer(source):
                name = match.group(1)
                if name in seen:
                    continue
                seen.add(name)
                args_raw = match.group(2)
                args = [a.strip().split("=")[0].strip().split(":")[0].strip()
                        for a in args_raw.split(",") if a.strip()]
                doc = self._get_docstring(source, match.start())
                functions.append({
                    "name": name,
                    "lineno": source[:match.start()].count("\n") + 1,
                    "docstring": doc,
                    "args": args,
                    "returns": None,
                    "decorators": [],
                })

        return functions

    def _extract_classes(self, source: str) -> list[dict]:
        classes = []
        for match in self.CLASS_RE.finditer(source):
            name = match.group(1)
            bases = [match.group(2)] if match.group(2) else []
            class_start = match.start()
            body_start = match.end()
            body_end = self._find_block_end(source, body_start)

            class_body = source[body_start:body_end]
            doc = self._get_docstring(source, class_start)

            methods = []
            for m in self.METHOD_RE.finditer(class_body):
                is_ctor = m.group(1) == "constructor"
                if is_ctor:
                    mname = "constructor"
                else:
                    mname = m.group(1)
                args_raw = m.group(2)
                args = [a.strip().split("=")[0].strip().split(":")[0].strip()
                        for a in args_raw.split(",") if a.strip()]
                m_start = class_start + m.start()
                m_doc = self._get_docstring(source, m_start)
                methods.append({
                    "name": mname,
                    "args": args,
                    "docstring": m_doc,
                })

            classes.append({
                "name": name,
                "docstring": doc,
                "methods": methods,
                "bases": bases,
            })

        return classes

    def _get_docstring(self, source: str, pos: int) -> str | None:
        prefix = source[max(0, pos - 2000):pos].rstrip()
        lines = prefix.split("\n")
        comments = []
        for line in reversed(lines):
            stripped = line.strip()
            if stripped.startswith("//"):
                comments.insert(0, stripped.lstrip("/").strip())
            elif stripped.startswith("*"):
                text = stripped.lstrip("*").strip()
                if text.startswith("/"):
                    text = text[1:].strip()
                comments.insert(0, text)
            elif stripped.endswith("*/"):
                text = stripped.rstrip("*").rstrip("/").strip()
                if text.startswith("*"):
                    text = text[1:].strip()
                comments.insert(0, text)
                break
            elif stripped.startswith("/**"):
                text = stripped.lstrip("/").lstrip("*").strip()
                comments.insert(0, text)
                break
            elif not stripped or stripped.startswith(("import", "export", "}")):
                continue
            else:
                break
        return " ".join(comments).strip() or None if comments else None

    def _find_block_end(self, source: str, start: int) -> int:
        depth = 0
        in_string = False
        string_char = None
        for i in range(start, min(start + 10000, len(source))):
            ch = source[i]
            if in_string:
                if ch == string_char and (i == 0 or source[i-1] != "\\"):
                    in_string = False
                continue
            if ch in ("'", '"', "`"):
                in_string = True
                string_char = ch
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        return len(source)


class HtmlParser(BaseParser):
    ext = ".html,.htm"
    language = "HTML"

    SCRIPT_RE = re.compile(
        r"<(?:script|script\s+[^>]*)>\s*//\s*<!\[CDATA\[(.*?)\]\]>\s*</script>",
        re.DOTALL,
    )
    SCRIPT_SRC_RE = re.compile(
        r"<script\s+[^>]*src\s*=\s*[\"']([^\"']+)[\"'][^>]*>\s*</script>"
    )
    TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>")
    META_DESC_RE = re.compile(
        r'<meta\s+[^>]*name\s*=\s*["\']description["\'][^>]*content\s*=\s*["\']([^"\']+)["\']',
        re.IGNORECASE,
    )
    FUNC_RE = re.compile(
        r"(?:function|const|let|var)\s+(\w+)\s*(?:=\s*(?:function|\([^)]*\)\s*=>))?\s*\(([^)]*)\)"
    )

    def _extract_module_doc(self, source: str) -> str | None:
        title = self.TITLE_RE.search(source)
        desc = self.META_DESC_RE.search(source)
        parts = []
        if title:
            parts.append(f"Title: {title.group(1)}")
        if desc:
            parts.append(desc.group(1))
        return " | ".join(parts) if parts else None

    def _extract_functions(self, source: str) -> list[dict]:
        functions = []
        seen = set()
        for match in self.FUNC_RE.finditer(source):
            name = match.group(1)
            if name in seen:
                continue
            seen.add(name)
            args_raw = match.group(2)
            args = [a.strip().split("=")[0].strip() for a in args_raw.split(",") if a.strip()]
            functions.append({
                "name": name,
                "lineno": source[:match.start()].count("\n") + 1,
                "docstring": None,
                "args": args,
                "returns": None,
                "decorators": [],
            })
        return functions

    def _extract_classes(self, source: str) -> list[dict]:
        return []


_PARSER_REGISTRY: dict[str, BaseParser] = {}


def get_parser(ext: str) -> BaseParser | None:
    if not _PARSER_REGISTRY:
        for cls in [JsTsParser, HtmlParser]:
            for e in cls.ext.split(","):
                _PARSER_REGISTRY[e.strip()] = cls()
    return _PARSER_REGISTRY.get(ext)


def parse_source_file(filepath: Path, source: str) -> dict:
    ext = filepath.suffix.lower()
    parser = get_parser(ext)
    if parser:
        return parser.parse(source)
    return {
        "module_docstring": None,
        "functions": [],
        "classes": [],
    }
