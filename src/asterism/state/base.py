from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from ..models import Assignment, DigestState, ItemState


class StateBackend(ABC):
    @abstractmethod
    def get(self, source: str, source_id: str) -> ItemState | None:
        raise NotImplementedError

    @abstractmethod
    def save(self, state: ItemState) -> None:
        raise NotImplementedError

    @abstractmethod
    def source_ids(self, source: str) -> set[str]:
        raise NotImplementedError

    @abstractmethod
    def sources(self) -> set[str]:
        """Every source name that has at least one recorded item."""
        raise NotImplementedError

    @abstractmethod
    def items(self, source: str) -> list[ItemState]:
        raise NotImplementedError

    @abstractmethod
    def items_between(self, start: str, end: str) -> list[ItemState]:
        """Items whose ``digest_time`` lies in ``[start, end)`` (ISO 8601 strings)."""
        raise NotImplementedError

    @abstractmethod
    def get_digest(self, source: str, level: str, period_start: str) -> DigestState | None:
        raise NotImplementedError

    @abstractmethod
    def save_digest(self, digest: DigestState) -> None:
        raise NotImplementedError

    @abstractmethod
    def digests(self, source: str | None = None, level: str | None = None) -> list[DigestState]:
        raise NotImplementedError

    @abstractmethod
    def get_assignment(self, source: str, source_id: str) -> Assignment | None:
        raise NotImplementedError

    @abstractmethod
    def save_assignment(self, assignment: Assignment) -> None:
        raise NotImplementedError

    @abstractmethod
    def assignments(self, decision: str | None = None) -> list[Assignment]:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self) -> StateBackend:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def digest_time_in_range(item: ItemState, start: str, end: str) -> bool:
    moment = item.digest_time
    return moment is not None and start <= moment < end


def iter_sorted(items: Iterable[ItemState]) -> list[ItemState]:
    return sorted(items, key=lambda item: (item.digest_time or "", item.source, item.source_id))
