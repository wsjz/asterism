"""Archive rolled-up digest documents below the archive root."""
from __future__ import annotations

import shutil

from ..config import Config
from ..models import DigestState
from ..state.base import StateBackend
from ..vault import VaultPathError, require_mounted, validated_target


def archive_digest(config: Config, state: StateBackend, digest: DigestState) -> str | None:
    """Copy or move one digest document to ``<archive.root>/<relative_path>``.

    Returns a message, or ``None`` when nothing was done. Never deletes with
    ``copy``; with ``move`` the source file leaves the vault after the copy
    succeeds. The digest's state becomes ``archived``.
    """
    if not config.archive.enabled:
        return None
    source = validated_target(config.vault, digest.relative_path)
    if not source.is_file():
        return None
    root = require_mounted(config.archive_root, "archive.root")
    target = validated_target(root, digest.relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if config.archive.mode == "move":
        source.unlink()
    state.save_digest(
        DigestState(
            level=digest.level,
            period_start=digest.period_start,
            period_end=digest.period_end,
            relative_path=digest.relative_path,
            state="archived",
            generated_at=digest.generated_at,
        )
    )
    verb = "moved" if config.archive.mode == "move" else "copied"
    return f"{digest.level} {digest.period_start} {verb} to {target}"


def archive_children(config: Config, state: StateBackend, children: list[DigestState]) -> list[str]:
    messages: list[str] = []
    for child in children:
        try:
            message = archive_digest(config, state, child)
        except VaultPathError as error:
            messages.append(f"archive skipped: {error}")
            break
        if message:
            messages.append(message)
    return messages
