from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re

from ..models import Origin, SourceItem
from ..normalize import derive_title
from ..normalize.punctuation import TAG_TERMINATORS
from .base import Source, SourceError


_TAG_PATTERN = re.compile(
    r"(?<![\w#])#([^\s#()\[\]{}<>\"'" + re.escape(TAG_TERMINATORS) + r"]+)"
)
_MAX_FILE_BYTES = 50 * 1024 * 1024


class MarkdownDirectorySource(Source):
    """Collect Markdown files without depending on a particular editor."""

    name = "markdown"
    output_name = "markdown"
    origin = Origin(adapter="markdown", producer="filesystem")

    def __init__(self, roots: tuple[Path, ...], *, vault: Path) -> None:
        if not roots:
            raise ValueError("configure at least one sources.markdown.roots path")
        self.roots = tuple(path.expanduser().resolve(strict=False) for path in roots)
        self.vault = vault.expanduser().resolve(strict=False)
        for root in self.roots:
            if (
                root == self.vault
                or root.is_relative_to(self.vault)
                or self.vault.is_relative_to(root)
            ):
                raise ValueError(
                    "Markdown input roots must not overlap the Asterism output vault"
                )

    def collect(self) -> list[SourceItem]:
        items: list[SourceItem] = []
        for root in self.roots:
            if not root.is_dir() or root.is_symlink():
                raise SourceError("Markdown root must be a regular directory, not a symlink")
            root_key = hashlib.sha256(os.fsencode(root)).hexdigest()[:16]
            for path in _markdown_files(root):
                items.append(_read_markdown(path, root, root_key))
        return items


def _markdown_files(root: Path):
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name.casefold())
        except OSError as error:
            raise SourceError("Markdown directory could not be read") from error
        for entry in entries:
            if entry.name.startswith(".") or entry.is_symlink():
                continue
            path = Path(entry.path)
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False) and path.suffix.lower() == ".md":
                    yield path
            except OSError as error:
                raise SourceError("Markdown directory entry could not be inspected") from error


def _read_markdown(path: Path, root: Path, root_key: str) -> SourceItem:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise SourceError("Markdown file resolves outside its configured root")
    try:
        stat = resolved.stat()
        if stat.st_size > _MAX_FILE_BYTES:
            raise SourceError("Markdown file exceeds the 50 MB safety limit")
        raw = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise SourceError("Markdown files must be UTF-8") from error
    except OSError as error:
        raise SourceError("Markdown file could not be read") from error

    front_matter, body = _split_front_matter(raw)
    front_title, front_tags = _front_matter_values(front_matter)
    author = _front_matter_scalar(front_matter, "author")
    # Obsidian convention: the file name is the note's title unless front matter says otherwise.
    title = derive_title(front_title, resolved.stem) or resolved.stem
    inline_tags = (match.group(1) for match in _TAG_PATTERN.finditer(body))
    tags = tuple(dict.fromkeys((*front_tags, *inline_tags)))
    relative = resolved.relative_to(root).as_posix()
    parent_path = resolved.parent.relative_to(root).as_posix()
    metadata: dict[str, str] = {"root": root.name, "path": relative}
    if front_matter and len(front_matter) <= 10_000:
        metadata["front_matter"] = front_matter

    created_timestamp = getattr(stat, "st_birthtime", stat.st_ctime)
    return SourceItem(
        source="markdown",
        source_id=f"{root_key}:{relative}",
        title=title,
        content_text=body,
        created_at=datetime.fromtimestamp(created_timestamp, timezone.utc),
        updated_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
        parent=None if parent_path == "." else parent_path,
        tags=tags,
        source_meta=metadata,
        author=author,
        origin=MarkdownDirectorySource.origin,
    )


def _front_matter_scalar(front_matter: str | None, key: str) -> str | None:
    if not front_matter:
        return None
    prefix = f"{key}:"
    for line in front_matter.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix):].strip().strip("\"'")
            return value[:1000] or None
    return None


def _split_front_matter(content: str) -> tuple[str | None, str]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, normalized
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() in {"---", "..."}:
            front_matter = "".join(lines[1:index]).rstrip("\n")
            return front_matter, "".join(lines[index + 1 :]).lstrip("\n")
    return None, normalized


def _front_matter_values(front_matter: str | None) -> tuple[str | None, tuple[str, ...]]:
    if not front_matter:
        return None, ()
    title: str | None = None
    tags: list[str] = []
    in_tags = False
    for line in front_matter.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("title:"):
            value = stripped.partition(":")[2].strip().strip("\"'")
            title = value[:10_000] or None
            in_tags = False
        elif stripped.startswith("tags:"):
            value = stripped.partition(":")[2].strip()
            in_tags = not value
            if value.startswith("[") and value.endswith("]"):
                value = value[1:-1]
            if value:
                tags.extend(_clean_tags(value.split(",")))
        elif in_tags and stripped.startswith("-"):
            tags.extend(_clean_tags([stripped[1:]]))
        else:
            in_tags = False
    return title, tuple(dict.fromkeys(tags))


def _clean_tags(values: list[str]) -> list[str]:
    return [
        cleaned
        for value in values
        if (cleaned := value.strip().strip("\"'").removeprefix("#"))
        and len(cleaned) <= 255
    ]
