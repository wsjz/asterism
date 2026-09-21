"""Map source names to adapter factories.

Names are the values accepted by ``--source``. ``opencli:<collection>`` is
reserved for the opencli adapter and resolves once that adapter exists.
"""
from __future__ import annotations

from typing import Callable

from ..config import Config
from .apple_notes import AppleNotesSource
from .base import Source
from .cubox import CuboxCLISource
from .flomo import FlomoExportSource
from .markdown import MarkdownDirectorySource
from .notion import NotionSource
from .opencli import OpencliSource


Factory = Callable[[Config], Source]

OPENCLI_PREFIX = "opencli:"


def _apple_notes(config: Config) -> Source:
    return AppleNotesSource(
        account=config.apple_notes_account,
        daily_log_folders=config.apple_notes_daily_log_folders,
        timezone=config.apple_notes_timezone,
        exclude_folders=config.apple_notes_exclude_folders,
    )


def _flomo(config: Config) -> Source:
    if config.flomo_export_path is None:
        raise ValueError("configure sources.flomo.export_path in asterism.yaml")
    return FlomoExportSource(config.flomo_export_path)


def _cubox(config: Config) -> Source:
    return CuboxCLISource()


def _markdown(config: Config) -> Source:
    if not config.markdown_roots:
        raise ValueError("configure sources.markdown.roots in asterism.yaml")
    return MarkdownDirectorySource(config.markdown_roots, vault=config.vault)


def _notion(config: Config) -> Source:
    return NotionSource(
        root_page_ids=config.notion_root_page_ids,
        data_source_ids=config.notion_data_source_ids,
        discover_all=config.notion_discover_all,
    )


FACTORIES: dict[str, Factory] = {
    "apple-notes": _apple_notes,
    "flomo": _flomo,
    "cubox": _cubox,
    "markdown": _markdown,
    "notion": _notion,
}

SOURCE_NAMES: tuple[str, ...] = tuple(FACTORIES)


def build_source(config: Config, name: str) -> Source:
    if name.startswith(OPENCLI_PREFIX):
        collection = config.opencli.collection(name[len(OPENCLI_PREFIX):])
        if collection is None:
            raise ValueError(
                f"unknown opencli collection {name[len(OPENCLI_PREFIX):]!r}; "
                "declare it under sources.opencli.collections"
            )
        return OpencliSource(collection, binary=config.opencli.binary)
    try:
        factory = FACTORIES[name]
    except KeyError:
        raise ValueError(f"unsupported source: {name}") from None
    return factory(config)


def configured_sources(config: Config) -> list[str]:
    """Names of sources that have enough configuration to run."""
    names = ["apple-notes"]
    if config.flomo_export_path is not None:
        names.append("flomo")
    names.append("cubox")
    if config.markdown_roots:
        names.append("markdown")
    if config.notion_root_page_ids or config.notion_data_source_ids or config.notion_discover_all:
        names.append("notion")
    names.extend(f"{OPENCLI_PREFIX}{collection.name}" for collection in config.opencli.collections)
    return names


def is_known_source(config: Config, name: str) -> bool:
    if name in FACTORIES:
        return True
    return name.startswith(OPENCLI_PREFIX) and config.opencli.collection(name[len(OPENCLI_PREFIX):]) is not None
