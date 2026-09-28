"""Collector interface.

A collector gathers or prepares evidence and never judges it. Work is split into
short units: `plan` returns the first units, and `run_unit` may return follow-up
units (e.g. the crawler's discovery step fans out into page-fetch batches).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from engine.context import CollectorContext, WorkUnit
from engine.schemas import EvidenceType


class Collector(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    version: ClassVar[str] = "1.0.0"
    produces: ClassVar[frozenset[EvidenceType]]
    requires: ClassVar[frozenset[EvidenceType]] = frozenset()

    @abstractmethod
    def plan(self, ctx: CollectorContext) -> list[WorkUnit]: ...

    @abstractmethod
    def run_unit(self, ctx: CollectorContext, unit: WorkUnit) -> list[WorkUnit]:
        """Do one unit of work; return any follow-up units."""
