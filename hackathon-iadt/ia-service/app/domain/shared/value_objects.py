"""
Shared Kernel — value objects reutilizados entre bounded contexts.
"""

from __future__ import annotations
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisId:
    """Identificador único de uma análise (UUID)."""
    value: str

    def __post_init__(self):
        # Valida formato UUID
        uuid.UUID(self.value)

    @classmethod
    def generate(cls) -> "AnalysisId":
        return cls(value=str(uuid.uuid4()))

    @classmethod
    def from_string(cls, value: str) -> "AnalysisId":
        return cls(value=value)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ReportId:
    """Identificador único de um relatório (UUID)."""
    value: str

    def __post_init__(self):
        uuid.UUID(self.value)

    @classmethod
    def generate(cls) -> "ReportId":
        return cls(value=str(uuid.uuid4()))

    @classmethod
    def from_string(cls, value: str) -> "ReportId":
        return cls(value=value)

    def __str__(self) -> str:
        return self.value
