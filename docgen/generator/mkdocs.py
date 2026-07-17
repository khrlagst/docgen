"""Generate mkdocs.yml and supporting structure for a MkDocs documentation site."""

MKDOCS_YML = """site_name: {name}
site_description: {description}
site_author: {author}

theme:
  name: material
  palette:
    - scheme: default
      primary: indigo
      accent: indigo
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - scheme: slate
      primary: indigo
      accent: indigo
      toggle:
        icon: material/brightness-4
        name: Switch to light mode
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.top
    - search.highlight
    - content.code.copy

markdown_extensions:
  - pymdownx.highlight:
      anchor_linenums: true
  - pymdownx.superfences
  - pymdownx.tabbed:
      alternate_style: true
  - admonition
  - pymdownx.details
  - tables
  - toc:
      permalink: true

nav:
  - Home: index.md
{nav_items}

plugins:
  - search
  - git-revision-date-localized:
      enable_creation_date: true

extra:
  generator: false
  social:
    - icon: fontawesome/brands/github
      link: https://github.com/{repo}
"""

NAV_ITEM = "  - {title}: {file}"


def generate_mkdocs_config(
    project_name: str,
    description: str = "",
    author: str = "",
    repo: str = "",
    files: list[dict] | None = None,
) -> str:
    nav_items = []
    if files:
        for f in files:
            nav_items.append(NAV_ITEM.format(title=f["title"], file=f["file"]))

    return MKDOCS_YML.format(
        name=project_name,
        description=description,
        author=author or "",
        repo=repo or project_name.lower().replace(" ", "-"),
        nav_items="\n".join(nav_items),
    )


def generate_index_frontmatter(title: str, description: str = "") -> str:
    return f"""---
description: {description}
---

# {title}

"""
