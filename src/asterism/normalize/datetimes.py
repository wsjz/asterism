from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any


_MILLISECOND_COLON = re.compile(
    r"(?P<clock>\d{2}:\d{2}:\d{2}):(?P<fraction>\d{1,6})(?P<zone>Z|[+-])"
)


def parse_datetime(value: Any) -> datetime | None:
    """Parse ISO 8601 text or a Unix timestamp; ``None`` and ``""`` give ``None``.

    Raises ``ValueError`` for anything else that cannot be interpreted.
    """
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as error:
            raise ValueError("invalid timestamp") from error
    if not isinstance(value, str) or len(value) > 100:
        raise ValueError("invalid date value")

    normalized = value.strip().replace("Z", "+00:00")
    normalized = _MILLISECOND_COLON.sub(
        lambda match: (
            f"{match.group('clock')}.{match.group('fraction')}"
            f"{'+00:00' if match.group('zone') == 'Z' else match.group('zone')}"
        ),
        normalized,
    )
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError("invalid date value") from error
