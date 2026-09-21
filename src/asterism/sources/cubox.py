from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Callable

from ..models import Origin, SourceItem
from ..normalize import derive_title
from .base import Source, SourceError
from .utils import parse_datetime


Runner = Callable[[list[str], int], str]


class CuboxCLISource(Source):
    name = "cubox"
    output_name = "cubox"
    origin = Origin(adapter="cubox", producer="cubox-cli")

    def __init__(self, runner: Runner | None = None) -> None:
        self._runner = runner or self._run_cli

    def collect(self) -> list[SourceItem]:
        active_cards = self._load_json(
            self._runner(["card", "list", "--all", "-o", "json"], 300),
            "card list",
        )
        archived_cards = self._load_json(
            self._runner(
                ["card", "list", "--archived", "--all", "-o", "json"], 300
            ),
            "archived card list",
        )
        # cubox-cli serializes an empty result as JSON null rather than [].
        # Normalize both forms so accounts with no archived cards still sync.
        if active_cards is None:
            active_cards = []
        if archived_cards is None:
            archived_cards = []
        if not isinstance(active_cards, list) or not isinstance(archived_cards, list):
            raise SourceError("Cubox CLI card list returned an unexpected payload")

        items: list[SourceItem] = []
        seen: set[str] = set()
        for card, archived in [
            *((card, False) for card in active_cards),
            *((card, True) for card in archived_cards),
        ]:
            if not isinstance(card, dict):
                raise SourceError("Cubox CLI returned a non-object card")
            card_id = _required_text(card, "id")
            if card_id in seen:
                continue
            seen.add(card_id)
            detail = self._load_json(
                self._runner(["card", "detail", "--id", card_id, "-o", "json"], 60),
                "card detail",
            )
            if not isinstance(detail, dict):
                raise SourceError("Cubox CLI card detail returned an unexpected payload")
            if _required_text(detail, "id") != card_id:
                raise SourceError("Cubox CLI card detail returned a mismatched identifier")
            items.append(self._to_item(detail, archived=archived))
        return items

    def _to_item(self, detail: dict[str, Any], *, archived: bool) -> SourceItem:
        card_id = _required_text(detail, "id")
        native_title = _optional_text(detail, "title") or _optional_text(detail, "article_title")
        content = _optional_text(detail, "content") or _optional_text(detail, "description") or ""
        url = _optional_text(detail, "url")
        title = derive_title(native_title, content, url)
        annotations = detail.get("annotations", [])
        if not isinstance(annotations, list):
            raise SourceError("Cubox CLI returned invalid annotations")
        content = _append_annotations(content, annotations)

        folder = detail.get("folder")
        if folder is not None and not isinstance(folder, dict):
            raise SourceError("Cubox CLI returned an invalid folder")
        # nested_name carries the full path for nested folders; top-level folders only
        # set name. Cubox's own "Uncategorized" folder is mirrored like any other.
        parent = (
            _optional_text(folder, "nested_name") or _optional_text(folder, "name") if folder else None
        )

        raw_tags = detail.get("tags", [])
        if not isinstance(raw_tags, list) or any(not isinstance(tag, str) for tag in raw_tags):
            raise SourceError("Cubox CLI returned invalid tags")
        tags = tuple(dict.fromkeys(tag.strip() for tag in raw_tags if tag.strip()))

        metadata = {
            key: value
            for key, value in {
                "domain": _optional_text(detail, "domain"),
                "read": detail.get("read") if isinstance(detail.get("read"), bool) else None,
                "starred": detail.get("starred") if isinstance(detail.get("starred"), bool) else None,
                "archived": archived,
            }.items()
            if value is not None
        }
        return SourceItem(
            source=self.name,
            source_id=card_id,
            title=title,
            content_text=content,
            created_at=parse_datetime(detail.get("create_time"), "Cubox CLI"),
            updated_at=parse_datetime(detail.get("update_time"), "Cubox CLI"),
            parent=parent,
            tags=tags,
            source_meta=metadata,
            url=url,
            author=_optional_text(detail, "author"),
            origin=self.origin,
        )

    @staticmethod
    def _load_json(payload: str, operation: str) -> Any:
        if len(payload) > 100 * 1024 * 1024:
            raise SourceError(f"Cubox CLI {operation} output exceeds the safety limit")
        try:
            return json.loads(payload)
        except json.JSONDecodeError as error:
            raise SourceError(f"Cubox CLI {operation} returned malformed JSON") from error

    @staticmethod
    def _run_cli(arguments: list[str], timeout_seconds: int) -> str:
        binary = shutil.which("cubox-cli")
        if binary is None:
            raise SourceError("cubox-cli is not installed or not available on PATH")
        try:
            completed = subprocess.run(
                [binary, *arguments],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise SourceError("Cubox CLI command timed out") from error
        except OSError as error:
            raise SourceError("Cubox CLI could not be started") from error
        if completed.returncode != 0:
            raise SourceError(
                f"Cubox CLI command failed with exit code {completed.returncode}; "
                "run 'cubox-cli auth status' in your terminal"
            )
        return completed.stdout


def _required_text(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise SourceError(f"Cubox CLI returned an invalid {key} field")
    return value


def _optional_text(record: dict[str, Any], key: str) -> str | None:
    value = record.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 50_000_000:
        raise SourceError(f"Cubox CLI returned an invalid {key} field")
    return value


def _append_annotations(content: str, annotations: list[Any]) -> str:
    rendered: list[str] = []
    for annotation in annotations:
        if not isinstance(annotation, dict):
            raise SourceError("Cubox CLI returned an invalid annotation")
        text = _optional_text(annotation, "text")
        note = _optional_text(annotation, "note")
        if text:
            rendered.append("\n".join(f"> {line}" for line in text.splitlines()))
        if note:
            rendered.append(note)
    if not rendered:
        return content
    prefix = f"{content.rstrip()}\n\n" if content.strip() else ""
    return prefix + "## Annotations\n\n" + "\n\n".join(rendered)
