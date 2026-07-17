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
                build_project_tree,
                summarize_workflows,
            )

            context["source_files"] = read_source_files(self.source_dir)
            context["source_modules"] = parse_project(self.source_dir)
            context["project_tree"] = build_project_tree(self.source_dir)
            context["workflow_summary"] = summarize_workflows(self.source_dir)

            from docgen.context.cli_surface import cli_surface_text

            context["cli_surface"] = cli_surface_text(self.source_dir)
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

        return context
