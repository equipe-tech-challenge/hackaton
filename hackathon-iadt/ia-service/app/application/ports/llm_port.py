"""
Application Layer — Ports para LLM.
Define as interfaces que a camada de aplicação espera do provider de LLM.
As implementações concretas ficam em infrastructure/llm/.
"""

from __future__ import annotations
from abc import ABC, abstractmethod

from app.domain.diagram_analysis.diagram_file import DiagramFile
from app.domain.diagram_analysis.extraction_result import ExtractionResult
from app.domain.report_generation.technical_report import TechnicalReport
from app.domain.report_generation.rag_context import RagContext
from app.domain.report_generation.qa_score import QAScore


class IVisionLLM(ABC):
    """Port para extração de componentes via LLM com capacidade de visão."""

    @abstractmethod
    def extract_components(self, diagram_file: DiagramFile) -> ExtractionResult:
        """
        Analisa a imagem do diagrama e extrai componentes, relacionamentos e padrões.
        Levanta ExtractionError em caso de falha.
        """


class ITextLLM(ABC):
    """Port para geração de texto/relatórios via LLM."""

    @abstractmethod
    def generate_report(
        self,
        extraction: ExtractionResult,
        rag_context: RagContext,
    ) -> TechnicalReport:
        """
        Gera o relatório técnico com análise de riscos.
        Levanta ReportGenerationError em caso de falha.
        """

    @abstractmethod
    def evaluate_quality(
        self,
        extraction: ExtractionResult,
        report: TechnicalReport,
    ) -> QAScore:
        """
        Avalia a qualidade do relatório gerado (fase LLM do QA).
        Retorna QAScore conservador em caso de falha (non-blocking).
        """
