from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import SourceItem


class SourceError(RuntimeError):
    """A source could not be collected without exposing private payloads."""


class Source(ABC):
    name: str
    output_name: str

    @abstractmethod
    def collect(self) -> list[SourceItem]:
        raise NotImplementedError
