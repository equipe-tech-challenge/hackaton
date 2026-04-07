"""
Application Layer — Port para Vector Store (RAG).
"""

from __future__ import annotations
from abc import ABC, abstractmethod

from app.domain.analysis.entities import ExtractionResult
from app.domain.report.value_objects import RagContext
from app.domain.shared.value_objects import AnalysisId


class IVectorStore(ABC):
    """Port para indexação e recuperação semântica de análises anteriores."""

    @abstractmethod
    def index(self, analysis_id: AnalysisId, extraction: ExtractionResult) -> None:
        """
        Indexa a extração atual no vector store para uso futuro.
        Non-blocking — falhas devem ser logadas, não propagadas.
        """

    @abstractmethod
    def retrieve_context(
        self,
        extraction: ExtractionResult,
        exclude_analysis_id: AnalysisId,
    ) -> RagContext:
        """
        Recupera análises similares e monta o contexto RAG.
        Retorna RagContext.empty() se não houver contexto disponível.
        """
