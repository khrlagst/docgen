import re

from pathlib import Path
from jinja2 import Environment, ChoiceLoader, FileSystemLoader, PackageLoader


def _oneline(value) -> str:
    """Collapse all whitespace (including newlines) into single spaces.

    Used for table-cell values (e.g. docstrings) so a multi-line value does not
    break the single-line rows that the markdown table extension requires.
    """
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def create_template_env(
    user_template_dir: str | None = None,
    template_name: str = "wiki",
) -> Environment:
    loaders = []

    templates_root = Path(__file__).parent.parent / "templates"

    if user_template_dir:
        user_path = Path(user_template_dir) / template_name
        if user_path.exists():
            loaders.append(FileSystemLoader(str(user_path)))

    # Directory-based templates (wiki/, manual/) live in their own folder.
    # Single-file templates (e.g. readme.md.j2) live directly under templates/.
    pkg_dir = f"templates/{template_name}"
    single_file = templates_root / f"{template_name}.md.j2"

    if single_file.exists():
        loaders.append(FileSystemLoader(str(templates_root)))
    else:
        try:
            loaders.append(PackageLoader("docgen", pkg_dir))
        except ValueError:
            pass
        loaders.append(FileSystemLoader(str(templates_root / template_name)))

    env = Environment(
        loader=ChoiceLoader(loaders),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["oneline"] = _oneline

    return env
