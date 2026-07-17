import questionary
from questionary import Choice, Separator


def collect_project_info() -> dict:
    """Walk the user through project setup interactively."""
    return questionary.form(
        name=questionary.text(
            "Project name:",
            default="MyProject",
        ),
        version=questionary.text(
            "Version:",
            default="0.1.0",
        ),
        description=questionary.text(
            "Short description:",
        ),
        language=questionary.select(
            "Primary language:",
            choices=["Python", "JavaScript", "TypeScript", "Go", "Rust", "Other"],
        ),
        include_api=questionary.confirm(
            "Include API reference?",
            default=True,
        ),
        include_changelog=questionary.confirm(
            "Include changelog?",
            default=True,
        ),
        include_guides=questionary.confirm(
            "Include user guides?",
            default=False,
        ),
    ).ask()
