"""Vault layout, path validation, and atomic writes shared by every stage."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile


NOTES_DIR = "notes"
ORIGIN_DIR = "origin"  # notes/<source>/origin/ holds the collected items
DIGEST_DIR = "digest"  # notes/<source>/digest/<level>/ holds the rollups over them
PROJECTS_DIR = "projects"  # one folder per piece, from candidate to published
PICKS_DIR = "picks"  # what was chosen out of the notes, one sheet per round
MACHINE_DIR = ".asterism"  # bookkeeping; a dot keeps it out of Obsidian's tree
# What a person writes as Markdown to shape the output — brief templates,
# platform rules — lives together and stays visible, because it is edited in
# Obsidian, which calls this kind of thing settings too.
SETTINGS_DIR = "settings"
STATE_DIR = f"{MACHINE_DIR}/state"
ARCHIVE_DIR = "archive"
INBOX_DIR = "inbox"


class VaultPathError(ValueError):
    """A path would escape its root or is otherwise unsafe to use."""


def normalize_vault(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    if resolved == Path(resolved.anchor):
        raise VaultPathError("the filesystem root cannot be used as a vault")
    return resolved


def validated_target(root: Path, relative_path: str | Path, *, within: Path | None = None) -> Path:
    """Resolve ``relative_path`` below ``root`` and require it to stay inside ``within``.

    ``within`` defaults to ``root``. The path may not be absolute or contain
    ``..`` components; the resolved result must remain below ``within``.
    """
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise VaultPathError("unsafe path: absolute or parent-directory components")
    boundary = (within or root).resolve(strict=False)
    target = (root / candidate).resolve(strict=False)
    if not target.is_relative_to(boundary):
        raise VaultPathError("path escapes its allowed directory")
    return target


def atomic_write(path: Path, content: str) -> None:
    """Write text to ``path`` through a temporary file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


NETWORK_FILESYSTEMS = frozenset({"smbfs", "afpfs", "nfs", "webdav", "cifs", "fuse-t", "macfuse"})


def mount_table(output: str | None = None) -> list[tuple[Path, str]]:
    """Parse ``/sbin/mount`` output into (mount point, filesystem type) pairs."""
    if output is None:
        try:
            output = subprocess.run(
                ["/sbin/mount"], capture_output=True, text=True, check=False, timeout=10
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return []
    table: list[tuple[Path, str]] = []
    for line in output.splitlines():
        # "<device> on <mount point> (<type>, <options>...)"
        head, separator, tail = line.rpartition(" (")
        if not separator or " on " not in head:
            continue
        mount_point = head.split(" on ", 1)[1]
        fs_type = tail.split(",", 1)[0].strip(") ")
        table.append((Path(mount_point), fs_type))
    return table


def network_filesystem(path: Path, table: list[tuple[Path, str]] | None = None) -> str | None:
    """The network filesystem type serving ``path``, or ``None`` for local storage."""
    resolved = path.resolve(strict=False)
    entries = mount_table() if table is None else table
    best: tuple[Path, str] | None = None
    for mount_point, fs_type in entries:
        if resolved == mount_point or resolved.is_relative_to(mount_point):
            if best is None or len(mount_point.parts) > len(best[0].parts):
                best = (mount_point, fs_type)
    if best is None:
        return None
    return best[1] if best[1].lower() in NETWORK_FILESYSTEMS else None


def require_mounted(root: Path, label: str) -> Path:
    """Refuse to act on a configured root that is not present, so nothing lands in a stand-in directory."""
    resolved = root.resolve(strict=False)
    if not resolved.is_dir():
        raise VaultPathError(f"{label} is not available at {resolved}; mount it or fix the configuration")
    return resolved
