from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Callable

from ...config import OpencliCollection
from ...models import Origin, SourceItem
from ..base import Source, SourceError
from .mapping import map_row

# (returncode, stdout, stderr)
Runner = Callable[[list[str], int], tuple[int, str, str]]

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_EMPTY = 66
EXIT_BRIDGE_DOWN = 69
EXIT_TIMEOUT = 75
EXIT_AUTH = 77
EXIT_CONFIG = 78

_MAX_OUTPUT_BYTES = 100 * 1024 * 1024
_COLLECT_TIMEOUT = 300

EXIT_HINTS = {
    EXIT_USAGE: "opencli rejected the command or its arguments; check the collection's command and args",
    EXIT_BRIDGE_DOWN: "opencli's Browser Bridge is not connected; open Chrome with the OpenCLI extension enabled",
    EXIT_TIMEOUT: "opencli timed out; try again later",
    EXIT_AUTH: "opencli needs you to log in to the site in Chrome first",
    EXIT_CONFIG: "opencli reported a configuration problem; run 'opencli doctor' in your terminal",
}


def run_opencli(arguments: list[str], timeout_seconds: int, *, binary: str | None = None) -> tuple[int, str, str]:
    executable = shutil.which(binary or "opencli")
    if executable is None:
        raise SourceError("opencli is not installed or not on PATH (npm install -g @jackwener/opencli)")
    try:
        completed = subprocess.run(
            [executable, *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise SourceError("opencli command timed out") from error
    except OSError as error:
        raise SourceError("opencli could not be started") from error
    return completed.returncode, completed.stdout, completed.stderr


class OpencliSource(Source):
    """One configured opencli collection: a single read-only command and its mapping."""

    def __init__(
        self,
        collection: OpencliCollection,
        *,
        binary: str | None = None,
        runner: Runner | None = None,
        version: str | None = None,
    ) -> None:
        self.collection = collection
        self.name = f"opencli-{collection.name}"
        self.output_name = self.name
        self.binary = binary
        self._runner = runner or (lambda args, timeout: run_opencli(args, timeout, binary=binary))
        self._version = version
        self.origin = Origin(
            adapter="opencli", producer=collection.producer, producer_version=self.version()
        )

    def version(self) -> str | None:
        if self._version is not None:
            return self._version
        try:
            code, stdout, _ = self._runner(["--version"], 30)
        except SourceError:
            return None
        if code != 0:
            return None
        text = stdout.strip().splitlines()[0] if stdout.strip() else ""
        self._version = text[:64] or None
        return self._version

    def command_line(self) -> list[str]:
        arguments = [*self.collection.command]
        for key, value in self.collection.args:
            if isinstance(value, bool):
                if value:
                    arguments.append(f"--{key}")
            else:
                arguments.extend((f"--{key}", str(value)))
        arguments.extend(("--format", "json"))
        return arguments

    def collect(self) -> list[SourceItem]:
        code, stdout, stderr = self._runner(self.command_line(), _COLLECT_TIMEOUT)
        if code == EXIT_EMPTY:
            return []
        if code != EXIT_OK:
            hint = EXIT_HINTS.get(code, "opencli command failed")
            raise SourceError(f"{hint} (exit code {code}, command {self.collection.producer})")
        rows = self._parse(stdout)
        items: list[SourceItem] = []
        seen: set[str] = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise SourceError(f"opencli {self.collection.producer} returned a non-object row")
            item = map_row(row, self.collection, self.name, self.origin)
            if item.source_id in seen:
                raise SourceError(
                    f"opencli {self.collection.producer} returned duplicate identity {item.source_id!r}; "
                    "map a different id or url column"
                )
            seen.add(item.source_id)
            items.append(item)
        return items

    def _parse(self, stdout: str) -> list[Any]:
        if len(stdout) > _MAX_OUTPUT_BYTES:
            raise SourceError("opencli output exceeds the 100 MB safety limit")
        try:
            payload = json.loads(stdout or "[]")
        except json.JSONDecodeError as error:
            raise SourceError(f"opencli {self.collection.producer} returned malformed JSON") from error
        if not isinstance(payload, list):
            raise SourceError(
                f"opencli {self.collection.producer} did not return a JSON array; "
                "the command may be unknown or not a data command"
            )
        return payload
