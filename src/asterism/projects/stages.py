"""Where a project's files live, from the configured production stages."""
from __future__ import annotations

from pathlib import Path

from ..config import ProjectConfig, Stage


# The order a piece is made in, which is the order these files are touched.
# With ``project.numbered`` on, a flat project folder shows it in the names, so
# the folder reads as the process instead of as an alphabet.
ARTIFACT_ORDER: tuple[str, ...] = (
    "project.md",   # the card, from `new` or `apply`
    "brief.md",     # what it could be, settled by `confirm`
    "draft.md",     # the writing, from `draft`
    "check.md",     # gate 2, from `check`
    "exports",      # the platform versions, from `adapt`
    "release.md",   # gate 3, from `release`
    "review.md",    # the retrospective, after publication
)


def stage_directory(config: ProjectConfig, stage: Stage) -> str:
    """The directory name of ``stage``: its explicit ``dir``, or its position and key."""
    if stage.dir:
        return stage.dir
    if not config.numbered:
        return stage.key
    position = next(index for index, entry in enumerate(config.stages, 1) if entry.key == stage.key)
    return f"{position:02d}-{stage.key}"


def stage_for_artifact(config: ProjectConfig, artifact: str) -> Stage | None:
    """The stage that owns ``artifact`` (``project.md``, ``draft.md`` …)."""
    return next((stage for stage in config.stages if artifact in stage.artifacts), None)


def artifact_path(config: ProjectConfig, artifact: str) -> str:
    """Where ``artifact`` is written inside a project directory.

    With the ``flat`` layout the Markdown files stay at the project root so
    Obsidian shows them beside each other, numbered by production order unless
    ``numbered`` is off; with ``staged`` they go into their stage's directory,
    which carries the number instead.
    """
    if config.layout == "flat":
        return _numbered(config, artifact)
    stage = stage_for_artifact(config, artifact)
    return f"{stage_directory(config, stage)}/{artifact}" if stage else artifact


def find_artifact(config: ProjectConfig, directory: Path, artifact: str) -> Path:
    """The file to read or write, keeping the name a project already uses.

    A project created before the numbers existed keeps its plain names, because
    renaming files would break every link already written to them. New files get
    the numbered name.
    """
    preferred = directory / artifact_path(config, artifact)
    if preferred.exists() or config.layout != "flat":
        return preferred
    plain = directory / artifact
    return plain if plain.exists() else preferred


def _numbered(config: ProjectConfig, artifact: str) -> str:
    if not config.numbered:
        return artifact
    head, _, rest = artifact.partition("/")
    try:
        position = ARTIFACT_ORDER.index(head) + 1
    except ValueError:
        return artifact
    numbered = f"{position:02d}-{head}"
    return f"{numbered}/{rest}" if rest else numbered
