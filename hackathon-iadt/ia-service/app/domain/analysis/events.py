"""
Analysis Bounded Context — Eventos de Domínio.
"""

from __future__ import annotations
from dataclasses import dataclass

from app.domain.shared.events import DomainEvent
from app.domain.shared.value_objects import AnalysisId


@dataclass(frozen=True)
class DiagramReceived(DomainEvent):
    """Emitido quando um diagrama é recebido (via upload ou SQS)."""
    analysis_id: AnalysisId
    file_name: str
    source: str  # "upload" | "sqs"


@dataclass(frozen=True)
class DiagramIngested(DomainEvent):
    """Emitido após validação e encoding bem-sucedidos do arquivo."""
    analysis_id: AnalysisId
    file_type: str
    file_size_kb: float


@dataclass(frozen=True)
class ComponentsExtracted(DomainEvent):
    """Emitido após extração de componentes via LLM Vision."""
    analysis_id: AnalysisId
    components_count: int
    patterns_count: int


@dataclass(frozen=True)
class AnalysisCompleted(DomainEvent):
    """Emitido quando o pipeline completa com sucesso."""
    analysis_id: AnalysisId
    qa_score: float


@dataclass(frozen=True)
class AnalysisFailed(DomainEvent):
    """Emitido quando qualquer etapa do pipeline falha."""
    analysis_id: AnalysisId
    step: str
    error_message: str
