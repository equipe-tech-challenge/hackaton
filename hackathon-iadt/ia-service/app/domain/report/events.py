"""
Report Bounded Context — Eventos de Domínio.
"""

from __future__ import annotations
from dataclasses import dataclass

from app.domain.shared.events import DomainEvent
from app.domain.shared.value_objects import AnalysisId, ReportId


@dataclass(frozen=True)
class ReportGenerated(DomainEvent):
    """Emitido quando um relatório técnico é gerado com sucesso."""
    report_id: ReportId
    analysis_id: AnalysisId
    rag_used: bool
    risks_count: int


@dataclass(frozen=True)
class QAValidationCompleted(DomainEvent):
    """Emitido após conclusão da validação de qualidade."""
    report_id: ReportId
    analysis_id: AnalysisId
    is_valid: bool
    completeness_score: float
