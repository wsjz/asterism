"""One version of the piece per platform, from rules kept in the vault.

The transform is deliberately dumb: the draft's prose, under the platform's own
rules file. What each platform wants differs by taste and keeps changing, so
the rules live in `platforms/<platform>.md` where they can be edited without
touching the code, and an agent rewrites the body to follow them.

An export is never overwritten once it has been edited. The file carries a
fingerprint of what the machine wrote; a file that no longer matches it was
edited by a person, whatever else they did or did not delete.
"""
from __future__ import annotations

from datetime import date
import hashlib
from pathlib import Path
import re

from ..config import Config
from ..projects import Project, ProjectError, find_artifact
from ..vault import atomic_write, validated_target
from .skeleton import MATERIAL_HEADING, draft_path


EXPORTS_DIR = "exports"
# Exports written before the fingerprint existed carried this marker instead,
# and deleting it was how a person said "mine". It is still honoured for them.
GENERATED_MARK = "<!-- asterism:generated -->"
_FINGERPRINT = re.compile(r"^fingerprint: (?P<hash>[0-9a-f]{64})$", re.MULTILINE)
_FRONT_MATTER_END = "\n---\n"

DEFAULT_RULES = """# {platform}

How a piece is rewritten for {platform}. Edit this file; Asterism only reads it
and never invents a rule, because what works on a platform is your judgment.

Whatever is written here is copied into every export for {platform}, so it is
in front of you while you rewrite instead of in another tab.

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
    target = validated_target(config.platforms_root, f"{platform}.md")
    if not target.is_file():
        atomic_write(target, DEFAULT_RULES.format(platform=platform))
    return target


def export_path(config: Config, project: Project, platform: str) -> Path:
    if project.directory is None:
        raise ProjectError(f"project {project.id} was not loaded from a directory")
    return find_artifact(config.project, project.directory, f"{EXPORTS_DIR}/{platform}.md")


def adapt_project(
    config: Config, project: Project, *, today: date | None = None
) -> list[tuple[str, Path, bool]]:
    """Write one export per platform; return (platform, path, written) for each.

    An export that a person has already edited is reported and left alone, so
    running this again after a draft change never throws away a rewrite. Edited
    means the file differs from what `adapt` last wrote, not that a marker was
    removed: a rewrite that touched only the prose is a rewrite all the same.
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
        if target.is_file() and is_edited(target.read_text(encoding="utf-8")):
            results.append((platform, target, False))
            continue
        atomic_write(target, _render(config, project, platform, rules, body, today))
        results.append((platform, target, True))
    return results


def is_edited(text: str) -> bool:
    """Whether a person has changed this export since `adapt` wrote it.

    The front matter records a fingerprint of everything below it; any change
    to that part, however small, is a person's and is kept. An export from
    before fingerprints is judged the old way, by whether its marker is gone.
    """
    match = _FINGERPRINT.search(_front_matter(text))
    if match is None:
        return GENERATED_MARK not in text
    return _fingerprint(_below_front_matter(text)) != match.group("hash")


def _front_matter(text: str) -> str:
    end = text.find(_FRONT_MATTER_END) if text.startswith("---\n") else -1
    return text[:end] if end != -1 else ""


def _below_front_matter(text: str) -> str:
    end = text.find(_FRONT_MATTER_END) if text.startswith("---\n") else -1
    return text[end + len(_FRONT_MATTER_END):] if end != -1 else text


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _render(
    config: Config,
    project: Project,
    platform: str,
    rules: Path,
    body: str,
    today: date | None,
) -> str:
    stamp = (today or date.today()).isoformat()
    below = [
        "",
        f"<!-- {rules.relative_to(config.vault).as_posix()} says, for {platform}:",
        "",
        _rules_body(rules),
        "",
        "Rewrite the piece to follow it. Once this file differs from what `adapt`",
        "wrote, `adapt` leaves it alone; delete this comment when you are done. -->",
        "",
    ]
    content = "\n".join(below) + body.strip() + "\n"
    head = [
        "---",
        f"project: {project.id}",
        f"platform: {platform}",
        f"generated: {stamp}",
        f"fingerprint: {_fingerprint(content)}",
        "---",
    ]
    return "\n".join(head) + "\n" + content


def _rules_body(rules: Path) -> str:
    """The platform's rules, minus its title, to travel inside the export."""
    try:
        text = rules.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "(the rules file could not be read)"
    lines = [line for line in text.splitlines() if not line.startswith("# ")]
    # an HTML comment cannot contain "--", which a rules file may well use
    return "\n".join(lines).replace("--", "—").strip() or "(no rules written yet)"


def _prose(draft: str) -> str:
    marker = draft.find(MATERIAL_HEADING)
    return draft if marker == -1 else draft[:marker]
