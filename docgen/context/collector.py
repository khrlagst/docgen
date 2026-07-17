from pathlib import Path


class ContextCollector:
    def __init__(self, source_dir: Path | None = None, language: str = "Python"):
        self.source_dir = source_dir
        self.language = language

    def collect(self, project_meta: dict) -> dict:
        context = {
            "metadata": project_meta,
            "source_modules": {},
            "source_files": {},
            "git_info": None,
        }

        if self.source_dir and self.source_dir.exists():
            from docgen.context.source import (
                read_source_files,
                parse_project,
                detect_language,
            )

            context["source_files"] = read_source_files(self.source_dir)
            context["source_modules"] = parse_project(self.source_dir)
            # project_tree / workflow_summary / cli_surface are expensive to
            # build (full source-tree walks + AST/CLI analysis). They are
            # computed lazily on first access via LazyContext so a template that
            # doesn't need them never pays the cost.
            context["_source_dir"] = self.source_dir

            detected = detect_language(self.source_dir, context["source_files"])
            if detected != "Unknown":
                context["metadata"]["language"] = detected

            from docgen.context.manifest import detect_manifest

            stack = detect_manifest(self.source_dir)
            if stack:
                # An inherited manifest (found only in a parent dir) must not
                # clobber a project whose own source files say otherwise — e.g.
                # a JS app nested inside a Python monorepo. File-extension
                # detection wins unless it found nothing. Inherited manifests
                # are still recorded for reference but never override language.
                context["metadata"]["stack"] = stack
                manifest_lang = stack.get("language")
                if manifest_lang and not (stack.get("inherited") and detected != "Unknown"):
                    context["metadata"]["language"] = manifest_lang

        try:
            from docgen.context.git_history import GitExtractor

            extractor = GitExtractor()
            context["git_info"] = {
                "contributors": extractor.get_contributors(),
                "changelog": extractor.get_changelog(),
                "version": extractor.get_version(),
            }
        except Exception:
            context["git_info"] = None

        return LazyContext(context)


class LazyContext:
    """Read-through wrapper that computes the expensive context fields only
    when they are first accessed.

    ``build_prompt`` reads ``project_tree``, ``workflow_summary`` and
    ``cli_surface``; for small projects or templates that don't use them, those
    walks are skipped entirely. All other keys pass through unchanged.
    """

    _LAZY_KEYS = ("project_tree", "workflow_summary", "cli_surface")

    def __init__(self, data: dict):
        object.__setattr__(self, "_data", data)
        object.__setattr__(self, "_computed", {})

    def __getitem__(self, key):
        data = object.__getattribute__(self, "_data")
        if key in self._LAZY_KEYS and key not in data:
            computed = object.__getattribute__(self, "_computed")
            if key not in computed:
                computed[key] = self._build(key)
            return computed[key]
        return data[key]

    def __setitem__(self, key, value):
        object.__getattribute__(self, "_data")[key] = value

    def __contains__(self, key):
        return key in object.__getattribute__(self, "_data") or key in self._LAZY_KEYS

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __getattr__(self, name):
        # Allow normal attribute access to fall back to the wrapped dict.
        return getattr(object.__getattribute__(self, "_data"), name)

    def _build(self, key: str):
        data = object.__getattribute__(self, "_data")
        source_dir = data.get("_source_dir")
        if source_dir is None:
            return None
        if key == "project_tree":
            from docgen.context.source import build_project_tree

            return build_project_tree(source_dir)
        if key == "workflow_summary":
            from docgen.context.source import summarize_workflows

            return summarize_workflows(source_dir)
        if key == "cli_surface":
            from docgen.context.cli_surface import cli_surface_text

            return cli_surface_text(source_dir)
        return None
