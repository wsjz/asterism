"""One version of the piece per platform, from rules kept in the vault.

The transform is deliberately dumb: the draft's prose, under the platform's own
rules file. What each platform wants differs by taste and keeps changing, so
the rules live in `platforms/<platform>.md` where they can be edited without
touching the code, and an agent rewrites the body to follow them.

An export is never overwritten once it has been edited: the machine writes the
first version and refreshes only the part it owns.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from ..config import Config
from ..projects import ContentProject, ProjectError, find_artifact
from ..vault import atomic_write, validated_target
from .skeleton import MATERIAL_HEADING, draft_path


EXPORTS_DIR = "exports"
PLATFORMS_DIR = "platforms"
GENERATED_MARK = "<!-- asterism:generated -->"

DEFAULT_RULES = """# {platform}

How a piece is rewritten for {platform}. Edit this file; Asterism only reads it.

## Shape

- Length:
- Opening:
- Headings:

## Must have

- [ ] a link back to the canonical version

## Never

-
"""


def platform_rules_path(config: Config, platform: str) -> Path:
    """The vault's rules for a platform, seeded empty the first time it is used."""
    target = validated_target(config.vault, f"{PLATFORMS_DIR}/{platform}.md")
    if not target.is_file():
        atomic_write(target, DEFAULT_RULES.format(platform=platform))
    return target


def export_path(config: Config, project: ContentProject, platform: str) -> Path:
    if project.directory is None:
        raise ProjectError(f"project {project.id} was not loaded from a directory")
    return find_artifact(config.project, project.directory, f"{EXPORTS_DIR}/{platform}.md")


def adapt_project(
    config: Config, project: ContentProject, *, today: date | None = None
) -> list[tuple[str, Path, bool]]:
    """Write one export per platform; return (platform, path, written) for each.

    An export that a person has already edited is reported and left alone, so
    running this again after a draft change never throws away a rewrite.
    """
    if not project.platforms:
        raise ProjectError(
            f"{project.id} has no platforms; add them to the card's `platforms` list"
        )
    try:
        draft = draft_path(config, project).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ProjectError(
            f"{project.id} has no draft to adapt; run `asterism draft {project.id}`"
        ) from error

    body = _prose(draft)
    results: list[tuple[str, Path, bool]] = []
    for platform in project.platforms:
        rules = platform_rules_path(config, platform)
        target = export_path(config, project, platform)
        if target.is_file() and GENERATED_MARK not in target.read_text(encoding="utf-8"):
            results.append((platform, target, False))
            continue
        atomic_write(target, _render(config, project, platform, rules, body, today))
        results.append((platform, target, True))
    return results


def _render(
    config: Config,
    project: ContentProject,
    platform: str,
    rules: Path,
    body: str,
    today: date | None,
) -> str:
    stamp = (today or date.today()).isoformat()
    head = [
        "---",
        f"project: {project.id}",
        f"platform: {platform}",
        f"generated: {stamp}",
        "---",
        "",
        GENERATED_MARK,
        "",
        f"<!-- rules: {rules.relative_to(config.vault).as_posix()};"
        " delete the marker above once this has been rewritten by hand -->",
        "",
    ]
    return "\n".join(head) + body.strip() + "\n"


def _prose(draft: str) -> str:
    marker = draft.find(MATERIAL_HEADING)
    return draft if marker == -1 else draft[:marker]
