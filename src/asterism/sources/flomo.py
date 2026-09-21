from __future__ import annotations

import hashlib
from pathlib import Path
import re
import zipfile

from ..models import Origin, SourceItem
from ..normalize import derive_title
from ..normalize.punctuation import TAG_TERMINATORS
from ..normalize.markdown import (
    Node,
    first_descendant_with_class,
    has_class,
    markdown_text,
    parse_html,
    plain_text,
    walk,
)
from .base import Source, SourceError
from .utils import parse_datetime


_TAG_PATTERN = re.compile(
    r"(?<![\w#])#([^\s#()\[\]{}<>\"'" + re.escape(TAG_TERMINATORS) + r"]+)"
)
_MAX_EXPORT_BYTES = 100 * 1024 * 1024


class FlomoExportSource(Source):
    name = "flomo"
    output_name = "flomo"
    origin = Origin(adapter="flomo", producer="html-export")

    def __init__(self, export_path: Path) -> None:
        self.export_path = export_path.expanduser().resolve(strict=False)

    def collect(self) -> list[SourceItem]:
        document = self._read_export()
        try:
            root = parse_html(document)
        except ValueError as error:
            raise SourceError("flomo export contains malformed HTML") from error

        memos = [node for node in walk(root) if has_class(node, "memo")]
        if not memos:
            raise SourceError("flomo export contains no memo records")

        items: list[SourceItem] = []
        used_ids: dict[str, int] = {}
        for memo in memos:
            time_node = first_descendant_with_class(memo, "time")
            content_node = first_descendant_with_class(memo, "content")
            if time_node is None or content_node is None:
                continue
            timestamp = plain_text(time_node).strip()
            content = markdown_text(content_node).strip()
            if not timestamp or not content:
                continue

            raw_id = _memo_identifier(memo, timestamp)
            occurrence = used_ids.get(raw_id, 0) + 1
            used_ids[raw_id] = occurrence
            source_id = raw_id if occurrence == 1 else f"{raw_id}:{occurrence}"
            title = derive_title(None, content)
            tags = tuple(dict.fromkeys(match.group(1) for match in _TAG_PATTERN.finditer(content)))
            created_at = parse_datetime(timestamp, "flomo export")

            items.append(
                SourceItem(
                    source=self.name,
                    source_id=source_id,
                    title=title,
                    content_text=content,
                    created_at=created_at,
                    updated_at=created_at,
                    parent=None,
                    tags=tags,
                    source_meta={"import_format": "html"},
                    origin=self.origin,
                )
            )

        if not items:
            raise SourceError("flomo export contains no readable memo records")
        return items

    def _read_export(self) -> str:
        if not self.export_path.is_file() or self.export_path.is_symlink():
            raise SourceError("flomo export path must be a regular HTML or ZIP file")
        suffix = self.export_path.suffix.lower()
        if suffix in {".html", ".htm"}:
            if self.export_path.stat().st_size > _MAX_EXPORT_BYTES:
                raise SourceError("flomo HTML export exceeds the 100 MB safety limit")
            try:
                return self.export_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise SourceError("flomo HTML export is not UTF-8") from error
        if suffix == ".zip":
            return self._read_zip()
        raise SourceError("flomo export must have an .html, .htm, or .zip extension")

    def _read_zip(self) -> str:
        try:
            with zipfile.ZipFile(self.export_path) as archive:
                candidates = [
                    info
                    for info in archive.infolist()
                    if not info.is_dir() and Path(info.filename).suffix.lower() in {".html", ".htm"}
                ]
                if not candidates:
                    raise SourceError("flomo ZIP export contains no HTML file")
                candidates.sort(
                    key=lambda info: (Path(info.filename).name.lower() != "index.html", info.filename)
                )
                selected = candidates[0]
                if selected.file_size > _MAX_EXPORT_BYTES:
                    raise SourceError("flomo HTML export exceeds the 100 MB safety limit")
                return archive.read(selected).decode("utf-8")
        except (zipfile.BadZipFile, UnicodeDecodeError) as error:
            raise SourceError("flomo ZIP export is invalid or not UTF-8") from error


def _memo_identifier(memo: Node, timestamp: str) -> str:
    for key in ("data-memo-id", "data-id", "id"):
        value = memo.attrs.get(key, "").strip()
        if value:
            return value[:4096]
    digest = hashlib.sha256(timestamp.encode("utf-8")).hexdigest()[:20]
    return f"export:{digest}"
