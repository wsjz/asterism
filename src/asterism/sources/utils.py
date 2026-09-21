from __future__ import annotations

from datetime import datetime
from typing import Any

from ..normalize.datetimes import parse_datetime as _parse_datetime
from .base import SourceError


def parse_datetime(value: Any, source_label: str) -> datetime | None:
    """Adapter-facing wrapper that reports failures as ``SourceError``."""
    try:
        return _parse_datetime(value)
    except ValueError as error:
        raise SourceError(f"{source_label} returned an invalid date") from error
