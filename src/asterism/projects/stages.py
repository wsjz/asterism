"""Where a project's files live: flat in its folder, numbered in production order."""
from __future__ import annotations

from pathlib import Path


# The order a piece is made in, which is the order these files are touched, so
# the folder reads as the process instead of as an alphabet. The machine writes
# the first two; the draft and the exports are the writer's.
ARTIFACT_ORDER: tuple[str, ...] = (
    "project.md",   # the card, from `new` or `apply`
    "brief.md",     # what it could be, settled by `confirm`
    "draft.md",     # the writing
    "exports",      # one version per platform
)


def artifact_path(artifact: str) -> str:
    """Where ``artifact`` is written inside a project directory, e.g. ``03-draft.md``."""
    head, _, rest = artifact.partition("/")
    try:
        position = ARTIFACT_ORDER.index(head) + 1
    except ValueError:
        return artifact
    numbered = f"{position:02d}-{head}"
    return f"{numbered}/{rest}" if rest else numbered


def find_artifact(directory: Path, artifact: str) -> Path:
    """The file to read or write inside a project directory."""
    return directory / artifact_path(artifact)
