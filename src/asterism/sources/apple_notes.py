from __future__ import annotations

from datetime import datetime, tzinfo
from importlib.resources import files
import json
import subprocess
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..config import RECENTLY_DELETED_FOLDERS
from ..models import Origin, SourceItem
from ..normalize import derive_title
from .base import Source, SourceError
from .fragments import note_date, split_daily_log
from .utils import parse_datetime


class AppleNotesError(SourceError):
    pass


class AppleNotesSource(Source):
    name = "apple_notes"
    output_name = "apple-notes"
    origin = Origin(adapter="apple_notes", producer="osascript")

    def __init__(
        self,
        account: str | None = None,
        timeout_seconds: int = 120,
        *,
        daily_log_folders: tuple[str, ...] = (),
        timezone: str | None = None,
        exclude_folders: tuple[str, ...] = RECENTLY_DELETED_FOLDERS,
    ) -> None:
        if account is not None and (not account.strip() or len(account) > 255):
            raise ValueError("Apple Notes account must be a short non-empty string")
        self.account = account.strip() if account else None
        self.timeout_seconds = timeout_seconds
        self.daily_log_folders = tuple(folder.strip() for folder in daily_log_folders if folder.strip())
        self.exclude_folders = tuple(folder.strip() for folder in exclude_folders if folder.strip())
        self.zone: tzinfo = _resolve_zone(timezone)

    def collect(self) -> list[SourceItem]:
        script = files("asterism.sources").joinpath("scripts/export_notes.applescript")
        command = ["/usr/bin/osascript", str(script)]
        if self.account:
            command.append(self.account)

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as error:
            raise AppleNotesError("/usr/bin/osascript is unavailable; macOS is required") from error
        except subprocess.TimeoutExpired as error:
            raise AppleNotesError("Apple Notes collection timed out") from error

        if completed.returncode != 0:
            raise AppleNotesError(
                f"Apple Notes collection failed with exit code {completed.returncode}; "
                "check macOS Automation permission for Notes"
            )

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise AppleNotesError("Apple Notes returned malformed data") from error
        if not isinstance(payload, list):
            raise AppleNotesError("Apple Notes returned an unexpected payload")
        items: list[SourceItem] = []
        for record in payload:
            items.extend(self._parse_record(record))
        return items

    def _is_excluded(self, folder: str) -> bool:
        top = folder.split("/", 1)[0]
        return top in self.exclude_folders

    def _is_daily_log(self, folder: str) -> bool:
        return any(folder == name or folder.endswith("/" + name) for name in self.daily_log_folders)

    def _parse_record(self, record: Any) -> list[SourceItem]:
        if not isinstance(record, dict):
            raise AppleNotesError("Apple Notes returned a non-object record")

        def text_field(name: str, *, required: bool = False) -> str:
            value = record.get(name)
            if value is None and not required:
                return ""
            if not isinstance(value, str) or (required and not value):
                raise AppleNotesError(f"invalid Apple Notes field: {name}")
            return value

        content = text_field("content_text")
        note_id = text_field("source_id", required=True)
        note_title = text_field("title")
        folder = text_field("folder")
        created_at = parse_datetime(record.get("created_at"), "Apple Notes")
        updated_at = parse_datetime(record.get("updated_at"), "Apple Notes")
        account = text_field("account")

        if folder and self._is_excluded(folder):
            return []
        if folder and self._is_daily_log(folder):
            return self._fragment_items(
                note_id, note_title, folder, content, created_at, updated_at, account
            )
        return [
            SourceItem(
                source=self.name,
                source_id=note_id,
                title=derive_title(note_title or None, content),
                content_text=content,
                created_at=created_at,
                updated_at=updated_at,
                parent=folder or None,
                tags=(),
                source_meta={"account": account},
                origin=self.origin,
            )
        ]

    def _fragment_items(
        self,
        note_id: str,
        note_title: str,
        folder: str,
        content: str,
        created_at: datetime | None,
        updated_at: datetime | None,
        account: str,
    ) -> list[SourceItem]:
        day = note_date(note_title, created_at)
        fragments = split_daily_log(
            content, title=note_title, day=day, note_created_at=created_at, zone=self.zone
        )
        return [
            SourceItem(
                source=self.name,
                source_id=f"{note_id}#{fragment.anchor}",
                title=derive_title(None, fragment.text),
                content_text=fragment.text,
                created_at=fragment.created_at,
                updated_at=updated_at,
                parent=f"{folder}/{note_title}" if note_title else folder,
                tags=(),
                source_meta={"account": account, "note_id": note_id, "fragment": fragment.anchor},
                origin=self.origin,
            )
            for fragment in fragments
        ]


def _resolve_zone(name: str | None) -> tzinfo:
    if name is None:
        local = datetime.now().astimezone().tzinfo
        assert local is not None
        return local
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f"unknown timezone: {name}") from error
