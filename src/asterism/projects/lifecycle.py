"""Dropping a project and bringing it back.

A piece that will not be finished keeps everything it had: the card, the
brief, and whatever else the project folder holds. Dropping it changes its
status and moves the folder to ``trash/``; restoring moves it home. Nothing
is deleted, so restarting is a decision, not a recovery.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil

from ..config import Config
from ..vault import atomic_write, validated_target
from .model import PROJECT_FILE, Project, ProjectError
from .paths import unique_directory
from .stages import find_artifact


def drop_project(config: Config, project: Project) -> Path:
    """Mark a project dropped and move its folder under ``trash/``."""
    if project.is_dropped:
        raise ProjectError(f"{project.id} is already dropped")
    return _move(config, project, "dropped", config.projects_root, config.trash_root)


def restore_project(config: Config, project: Project) -> Path:
    """Bring a dropped project back as a candidate."""
    if not project.is_dropped:
        raise ProjectError(f"{project.id} is not dropped")
    return _move(config, project, "candidate", config.trash_root, config.projects_root)


def _move(config: Config, project: Project, status: str, source_root: Path, target_root: Path) -> Path:
    directory = project.directory
    if directory is None:
        raise ProjectError(f"project {project.id} was not loaded from a directory")
    try:
        relative = directory.relative_to(source_root).as_posix()
    except ValueError as error:
        raise ProjectError(f"{project.id} is not below {source_root}") from error

    chosen = unique_directory(config, relative, root=target_root)
    target = validated_target(target_root, chosen)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(directory), str(target))

    moved = replace(project, status=status, directory=target)
    atomic_write(find_artifact(config.project, target, PROJECT_FILE), moved.to_markdown())
    _prune_empty(directory.parent, source_root)
    return target


def _prune_empty(directory: Path, root: Path) -> None:
    """Remove the year folders a move left behind, never the root itself."""
    while directory != root and directory.is_dir() and not any(directory.iterdir()):
        directory.rmdir()
        directory = directory.parent
