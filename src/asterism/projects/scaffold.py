"""Creating a project: its directory, card, and brief, from the vault's templates."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from importlib.resources import files
from pathlib import Path
import re

from ..config import Config
from ..links import link_to
from ..rendering import parse_front_matter
from ..vault import atomic_write, validated_target
from .model import BRIEF_FILE, PROJECT_FILE, ContentProject, ProjectError
from .paths import next_id, render_path, unique_directory
from .stages import artifact_path


PROJECT_TEMPLATE = "project.md"
DEFAULT_BRIEF_TEMPLATE = "brief-default.md"
MAX_QUOTE_CHARS = 2000  # a brief is a working document, not a copy of the archive
_PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")


def ensure_template(config: Config, name: str) -> Path:
    """The vault's copy of a template, seeded from the packaged default once.

    Seeding makes the templates discoverable: they appear in the vault the
    first time a project is created, and editing them changes every later
    project without touching the code.
    """
    target = validated_target(config.templates_root, name)
    if not target.is_file():
        packaged = files("asterism").joinpath(f"templates/{name}")
        if not packaged.is_file():
            packaged = files("asterism").joinpath(f"templates/{DEFAULT_BRIEF_TEMPLATE}")
        atomic_write(target, packaged.read_text(encoding="utf-8"))
    return target


def render_template(text: str, values: dict[str, str]) -> str:
    """Substitute ``{{name}}`` placeholders, leaving unknown ones visible."""
    return _PLACEHOLDER.sub(lambda match: values.get(match.group(1), match.group(0)), text)


def brief_template_name(config: Config, pillar: str | None) -> str:
    configured = config.content.pillar(pillar)
    if configured is not None and configured.brief:
        return Path(configured.brief).name
    return f"brief-{pillar}.md" if pillar else DEFAULT_BRIEF_TEMPLATE


def create_project(
    config: Config,
    *,
    title: str,
    pillar: str | None = None,
    type_: str | None = None,
    platforms: tuple[str, ...] = (),
    sources: tuple[str, ...] = (),
    status: str = "candidate",
    today: date | None = None,
    promise: str | None = None,
) -> ContentProject:
    """Create the project folder with its card and brief, and return the card."""
    if not title.strip():
        raise ProjectError("a project needs a title")
    _validate(config, pillar, type_, platforms)
    created = today or date.today()
    project_id = next_id(config, today=created, pillar=pillar, type_=type_)
    relative = unique_directory(
        config, render_path(config, project_id=project_id, title=title.strip(), created=created, pillar=pillar, type_=type_)
    )
    directory = validated_target(config.content_root, relative)

    project = ContentProject(
        id=project_id,
        title=title.strip(),
        status=status,
        pillar=pillar,
        type=type_,
        promise=promise,
        primary=platforms[0] if platforms else None,
        platforms=platforms,
        created=created,
        sources=sources,
        directory=directory,
    )
    values = _values(config, project, directory)

    card_body = render_template(ensure_template(config, PROJECT_TEMPLATE).read_text(encoding="utf-8"), values)
    brief_text = render_template(
        ensure_template(config, brief_template_name(config, pillar)).read_text(encoding="utf-8"), values
    )
    atomic_write(directory / artifact_path(config.project, PROJECT_FILE), project.with_body(card_body).to_markdown())
    atomic_write(directory / artifact_path(config.project, BRIEF_FILE), brief_text.rstrip() + "\n")
    return replace(project, body=card_body)


def _validate(config: Config, pillar: str | None, type_: str | None, platforms: tuple[str, ...]) -> None:
    known_pillars = tuple(entry.key for entry in config.content.pillars)
    if pillar is not None and known_pillars and pillar not in known_pillars:
        raise ProjectError(f"unknown pillar {pillar!r}; configured pillars are {', '.join(known_pillars)}")
    if type_ is not None and type_ not in config.content.types:
        raise ProjectError(f"unknown type {type_!r}; configured types are {', '.join(config.content.types)}")
    unknown = [name for name in platforms if name not in config.content.platforms]
    if unknown:
        raise ProjectError(
            f"unknown platforms: {', '.join(unknown)}; configured platforms are {', '.join(config.content.platforms)}"
        )


def _quote_source(config: Config, relative: str, card: Path) -> str:
    """A collected item as a heading, its date, and its text quoted.

    The brief has to be readable on its own while writing, so the fragment
    travels with the link instead of only being pointed at.
    """
    label = Path(relative).stem
    heading = f"### {link_to(config.links, config.vault, relative, label, from_file=card)}"
    try:
        fields, body = parse_front_matter((config.vault / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return f"{heading}\n\n> the note could not be read"
    created = str(fields.get("created_at") or "")[:10]
    source = str(fields.get("source") or "")
    meta = " - ".join(part for part in (created, source) if part)
    text = body.strip()
    if len(text) > MAX_QUOTE_CHARS:
        text = text[:MAX_QUOTE_CHARS].rstrip() + " ..."
    quote = "\n".join(f"> {line}" if line else ">" for line in text.splitlines()) or "> (empty)"
    return f"{heading}\n\n{meta}\n\n{quote}" if meta else f"{heading}\n\n{quote}"


def _values(config: Config, project: ContentProject, directory: Path) -> dict[str, str]:
    card = directory / artifact_path(config.project, PROJECT_FILE)
    brief_relative = (directory / artifact_path(config.project, BRIEF_FILE)).relative_to(config.vault).as_posix()
    quoted = [_quote_source(config, source, card) for source in project.sources]
    return {
        "id": project.id,
        "title": project.title,
        "pillar": project.pillar or "",
        "type": project.type or "",
        "status": project.status,
        "date": project.created.isoformat() if project.created else "",
        "promise": project.promise or "",
        "platforms": ", ".join(project.platforms),
        "brief_link": link_to(config.links, config.vault, brief_relative, "Brief", from_file=card),
        "sources": "\n\n".join(quoted),
    }
