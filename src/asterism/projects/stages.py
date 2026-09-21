"""Where a project's files live, from the configured production stages."""
from __future__ import annotations

from ..config import ProjectConfig, Stage


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
    Obsidian shows them beside each other; with ``staged`` they go into their
    stage's directory.
    """
    if config.layout == "flat":
        return artifact
    stage = stage_for_artifact(config, artifact)
    return f"{stage_directory(config, stage)}/{artifact}" if stage else artifact
