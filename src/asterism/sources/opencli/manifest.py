"""Validate configured collections against ``opencli list --format json``."""
from __future__ import annotations

import json
from typing import Any

from ...config import OpencliCollection
from ..base import SourceError
from .source import Runner

_MAX_MANIFEST_BYTES = 50 * 1024 * 1024


def load_manifest(runner: Runner) -> list[dict[str, Any]]:
    code, stdout, _ = runner(["list", "--format", "json"], 120)
    if code != 0:
        raise SourceError(f"'opencli list' failed with exit code {code}")
    if len(stdout) > _MAX_MANIFEST_BYTES:
        raise SourceError("opencli manifest exceeds the safety limit")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise SourceError("'opencli list' returned malformed JSON") from error
    if not isinstance(payload, list):
        raise SourceError("'opencli list' did not return a JSON array")
    return [entry for entry in payload if isinstance(entry, dict)]


def find_command(manifest: list[dict[str, Any]], collection: OpencliCollection) -> dict[str, Any] | None:
    site, name = collection.command
    for entry in manifest:
        if entry.get("site") == site and entry.get("name") == name:
            return entry
    return None


def validate_collection(collection: OpencliCollection, manifest: list[dict[str, Any]]) -> list[str]:
    """Human-readable problems; an empty list means the collection may run."""
    entry = find_command(manifest, collection)
    problems: list[str] = []
    if entry is None:
        return [f"{collection.producer}: command not found in 'opencli list'"]
    if entry.get("access") != "read":
        problems.append(f"{collection.producer}: access is {entry.get('access')!r}; only read commands may be collected")
    columns = entry.get("columns")
    if isinstance(columns, list) and columns:
        declared = {str(column) for column in columns}
        for field in collection.map.mapped_fields():
            if field not in declared:
                problems.append(f"{collection.producer}: mapped field {field!r} is not a declared column")
    declared_args = {
        str(arg.get("name")) for arg in entry.get("args", []) if isinstance(arg, dict) and arg.get("name")
    }
    for key, _ in collection.args:
        if declared_args and key not in declared_args:
            problems.append(f"{collection.producer}: unknown argument --{key}")
    if entry.get("browser"):
        problems.append(
            f"{collection.producer}: needs the browser (Chrome with the OpenCLI extension and a login) — informational"
        )
    return problems
