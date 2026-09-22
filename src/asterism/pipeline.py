from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from .models import ItemState, SyncResult
from .rendering import content_hash, note_filename, note_relative_dir, render_markdown, unique_filename
from .sources.base import Source
from .state.base import StateBackend
from .vault import NOTES_DIR, ORIGIN_DIR, VaultPathError, atomic_write, validated_target


class Pipeline:
    def __init__(self, source: Source, state: StateBackend, vault: Path) -> None:
        self.source = source
        self.state = state
        self.vault = vault.resolve(strict=False)
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", source.output_name) is None:
            raise ValueError("source output_name must be a lowercase URL-style slug")
        # Output is always <vault>/notes/<source.output_name>/. The vault comes
        # from --vault; it is not implicitly the application source repository.
        # New items are written under origin/; anything already recorded elsewhere in
        # the source's tree is a previous layout and is moved, not rejected.
        self.source_root = (self.vault / NOTES_DIR / source.output_name).resolve(strict=False)
        self.output_dir = (self.source_root / ORIGIN_DIR).resolve(strict=False)
        self._taken: dict[str, set[str]] = {}

    def sync(self, *, dry_run: bool = False) -> SyncResult:
        items = self.source.collect()
        seen: set[str] = set()
        self._taken = self._occupied_names()
        created = updated = unchanged = 0
        now = datetime.now(timezone.utc).isoformat()

        if not dry_run:
            self.output_dir.mkdir(parents=True, exist_ok=True)

        for item in items:
            if item.source != self.source.name:
                raise ValueError("source returned an item with the wrong source name")
            if item.source_id in seen:
                raise ValueError(f"source returned a duplicate identifier: {item.source_id!r}")
            seen.add(item.source_id)

            previous = self.state.get(item.source, item.source_id)
            relative_path = self._relative_path(item, previous)
            target = self._validated_target(relative_path)
            moved_from = (
                self._validated_target(previous.relative_path, within=self.source_root)
                if previous is not None and previous.relative_path != relative_path
                else None
            )
            rendered = render_markdown(item)
            digest = content_hash(rendered)

            if previous is None:
                created += 1
                changed = True
            elif previous.content_hash != digest or moved_from is not None or not target.is_file():
                updated += 1
                changed = True
            else:
                unchanged += 1
                changed = False

            if not dry_run:
                if changed:
                    atomic_write(target, rendered)
                    if moved_from is not None and moved_from != target and moved_from.is_file():
                        moved_from.unlink()  # the item moved in its source; follow it
                        _prune_empty(moved_from.parent, self.source_root)
                self.state.save(
                    ItemState(
                        source=item.source,
                        source_id=item.source_id,
                        relative_path=relative_path,
                        content_hash=digest,
                        source_updated_at=(
                            item.updated_at.isoformat() if item.updated_at else None
                        ),
                        last_seen_at=now,
                        first_seen_at=(
                            previous.first_seen_at if previous is not None and previous.first_seen_at else now
                        ),
                        source_created_at=(
                            item.created_at.isoformat() if item.created_at else None
                        ),
                        title=item.title,
                    )
                )

        missing = len(self.state.source_ids(self.source.name) - seen)
        return SyncResult(
            discovered=len(items),
            created=created,
            updated=updated,
            unchanged=unchanged,
            missing=missing,
            dry_run=dry_run,
        )

    def _occupied_names(self) -> dict[str, set[str]]:
        """File names already used per directory, from state, so new items never collide."""
        taken: dict[str, set[str]] = {}
        for recorded in self.state.items(self.source.name):
            directory, _, filename = recorded.relative_path.rpartition("/")
            taken.setdefault(directory, set()).add(filename)
        return taken

    def _relative_path(self, item, previous) -> str:
        """Mirror the source hierarchy; keep a recorded file name, or pick a unique one from the title."""
        directory = note_relative_dir(item)
        base = f"{NOTES_DIR}/{self.source.output_name}/{ORIGIN_DIR}"
        folder = f"{base}/{directory}" if directory else base
        if previous is not None:
            filename = previous.relative_path.rsplit("/", 1)[-1]
            if previous.relative_path.rpartition("/")[0] != folder:
                filename = self._claim(folder, filename)  # moving: avoid a clash in the new folder
        else:
            filename = self._claim(folder, note_filename(item))
        return f"{folder}/{filename}"

    def _claim(self, folder: str, filename: str) -> str:
        names = self._taken.setdefault(folder, set())
        on_disk = (self.vault / folder)
        if on_disk.is_dir():
            names.update(entry.name for entry in on_disk.iterdir())
        chosen = unique_filename(filename, names)
        names.add(chosen)
        return chosen

    def _validated_target(self, relative_path: str, within: Path | None = None) -> Path:
        try:
            return validated_target(self.vault, relative_path, within=within or self.output_dir)
        except VaultPathError as error:
            raise ValueError(f"state contains an unsafe output path: {error}") from error


def _prune_empty(directory: Path, root: Path) -> None:
    """Remove folders a move emptied, never the source root itself."""
    while directory != root and directory.is_dir() and not any(directory.iterdir()):
        directory.rmdir()
        directory = directory.parent
