"""Machine-readable command output.

An agent drives Asterism through the same commands a person uses, so every
command that reports something can print one JSON object instead of prose.
The keys are part of the interface: add to them, do not rename them.

The object always carries ``command`` and ``ok``; everything else belongs to
the command. Nothing else is written to stdout in this mode, so a caller can
parse the whole stream.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
import json
from pathlib import Path
import sys
from typing import Any


def emit(command: str, payload: dict[str, Any], *, ok: bool = True) -> None:
    """Print one JSON object for ``command`` on stdout."""
    document = {"command": command, "ok": ok, **payload}
    json.dump(document, sys.stdout, ensure_ascii=False, sort_keys=True, default=_plain)
    sys.stdout.write("\n")


def emit_error(command: str, message: str, *, hint: str | None = None) -> None:
    """Report a failure in the same shape, with the command that would fix it."""
    payload: dict[str, Any] = {"error": message}
    if hint:
        payload["hint"] = hint
    emit(command, payload, ok=False)


def _plain(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    return str(value)
