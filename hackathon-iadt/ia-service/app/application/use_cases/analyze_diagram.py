"""
Application Layer — Use Case: Analyze Diagram.

AnalyzeDiagramUseCase orquestra o pipeline completo de análise E2E:
  ingestão → extração → RAG → relatório → QA

Aplica o padrão de inversão de dependência:
- Recebe as implementações de repositório e LLM via injeção (ports)
- Não conhece detalhes de banco, HTTP ou LLM provider
- Emite progresso via callback opcional (para SSE streaming)
"""

from __future__ import annotations
import time
from typing import Callable, Optional

from app.domain.analysis.aggregate import AnalysisAggregate
from app.domain.analysis.value_objects import DiagramFile, AnalysisStatus
from app.domain.analysis.entities import ExtractionResult
from app.domain.analysis.repository import IAnalysisRepository
from app.domain.report.aggregate import ReportAggregate
from app.domain.report.entities import TechnicalReport
from app.domain.report.value_objects import QAScore, RagContext
from app.domain.report.services import GuardrailService
from app.domain.report.repository import IReportRepository
from app.domain.shared.value_objects import AnalysisId, ReportId

from app.application.ports.llm_port import IVisionLLM, ITextLLM
from app.application.ports.vector_store_port import IVectorStore

from app.utils.exceptions import (
    IngestionError, QAError, RAGError,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Tipo do callback de progresso: (step, status, data) -> None
StepCallback = Callable[[str, str, dict], None]


class AnalyzeDiagramUseCase:
    """
    Caso de uso principal — análise E2E de diagrama de arquitetura.

    Dependências injetadas (inversão de controle):
        analysis_repo:   IAnalysisRepository
        report_repo:     IReportRepository
        vision_llm:      IVisionLLM
        text_llm:        ITextLLM
        vector_store:    IVectorStore
        guardrail_svc:   GuardrailService
    """

    def __init__(
        self,
        analysis_repo: IAnalysisRepository,
        report_repo: IReportRepository,
        vision_llm: IVisionLLM,
        text_llm: ITextLLM,
        vector_store: IVectorStore,
        guardrail_svc: Optional[GuardrailService] = None,
    ):
        self._analysis_repo = analysis_repo
        self._report_repo = report_repo
        self._vision_llm = vision_llm
        self._text_llm = text_llm
        self._vector_store = vector_store
        self._guardrail = guardrail_svc or GuardrailService()

    def execute(
        self,
        file_bytes: bytes,
        file_name: str,
        s3_key: Optional[str] = None,
        sqs_message_id: Optional[str] = None,
        source: str = "upload",
        on_step: Optional[StepCallback] = None,
    ) -> dict:
        """
        Executa o pipeline completo.

        Returns:
            dict com analysis_id, status, report, qa
        """
        def emit(step: str, status: str, data: dict = None):
            if on_step:
                on_step(step, status, data or {})

        # ── Cria o aggregate de análise ────────────────────────────
        analysis_id = AnalysisId.generate()
        analysis = AnalysisAggregate.create(
            analysis_id=analysis_id,
            file_name=file_name,
            file_type=file_name.rsplit(".", 1)[-1].lower(),
            s3_key=s3_key,
            sqs_message_id=sqs_message_id,
            source=source,
        )
        self._analysis_repo.save(analysis)
        log = logger.bind(analysis_id=str(analysis_id))
        log.info("use_case.analyze_diagram.start")

        try:
            # ── Etapa 1: Ingestão ──────────────────────────────────
            emit("ingestion", "running")
            t0 = time.time()
            log.info("pipeline.step", step="ingestion")

            diagram_file = self._ingest(file_bytes, file_name)
            analysis.start_ingestion(diagram_file)
            self._analysis_repo.update_status(analysis)

            emit("ingestion", "done", {
                "file_type": diagram_file.file_type.value,
                "file_size_kb": diagram_file.file_size_kb,
                "elapsed": round(time.time() - t0, 1),
            })

            # ── Etapa 2: Extração via LLM Vision ───────────────────
            emit("extraction", "running")
            t0 = time.time()
            log.info("pipeline.step", step="extraction")

            extraction = self._vision_llm.extract_components(diagram_file)
            analysis.complete_extraction(extraction)
            self._analysis_repo.save(analysis)

            emit("extraction", "done", {
                "components_count": len(extraction.components),
                "relationships_count": len(extraction.relationships),
                "patterns": [str(p) for p in extraction.patterns],
                "elapsed": round(time.time() - t0, 1),
            })

            # ── Etapa 3: RAG (non-blocking) ────────────────────────
            emit("rag", "running")
            t0 = time.time()
            log.info("pipeline.step", step="rag")

            rag_context = self._retrieve_rag_context(analysis_id, extraction, log)

            emit("rag", "done", {
                "has_context": rag_context.has_context,
                "similar_count": rag_context.similar_analyses_count,
                "elapsed": round(time.time() - t0, 1),
            })

            # ── Etapa 4: Geração de Relatório ──────────────────────
            emit("report", "running")
            t0 = time.time()
            log.info("pipeline.step", step="report")

            report = self._text_llm.generate_report(extraction, rag_context)
            self._guardrail.validate(report, extraction)

            report_aggregate = ReportAggregate.create(
                report_id=ReportId.generate(),
                analysis_id=analysis_id,
            )
            report_aggregate.attach_report(report)

            severity = report.risk_severity_summary
            emit("report", "done", {
                "components_count": len(report.components_identified),
                "risks_count": len(report.architectural_risks),
                "severity": severity,
                "recommendations_count": len(report.recommendations),
                "rag_used": report.rag_used,
                "elapsed": round(time.time() - t0, 1),
            })

            # ── Etapa 5: QA ────────────────────────────────────────
            emit("qa", "running")
            t0 = time.time()
            log.info("pipeline.step", step="qa")

            qa_score = self._evaluate_quality(extraction, report, log)
            report_aggregate.attach_qa(qa_score)

            if not qa_score.is_valid:
                raise QAError(
                    f"Relatório rejeitado pelo QA: {qa_score.issues_found}",
                    step="qa",
                    analysis_id=str(analysis_id),
                )

            emit("qa", "done", {
                "is_valid": qa_score.is_valid,
                "completeness_score": qa_score.completeness_score,
                "issues_count": len(qa_score.issues_found),
                "elapsed": round(time.time() - t0, 1),
            })

            # ── Persistência final ─────────────────────────────────
            self._report_repo.save(report_aggregate)
            analysis.complete(qa_score.completeness_score)
            self._analysis_repo.update_status(analysis)

            log.info("use_case.analyze_diagram.done", qa_score=qa_score.completeness_score)

            result = {
                "analysis_id": str(analysis_id),
                "status": AnalysisStatus.ANALYZED.value,
                "report": report.to_dict(),
                "qa": qa_score.to_dict(),
            }
            emit("done", "complete", result)
            return result

        except QAError as e:
            log.error("pipeline.qa_rejected", issues=str(e))
            analysis.fail(e.step, str(e))
            self._analysis_repo.update_status(analysis)
            emit("qa", "error", {"error": str(e), "error_type": "QAError"})
            raise

        except Exception as e:
            step = getattr(e, "step", "pipeline")
            log.error("pipeline.error", step=step, error=str(e))
            analysis.fail(step, str(e))
            self._analysis_repo.update_status(analysis)
            emit(step, "error", {"error": str(e), "error_type": type(e).__name__})
            raise

    # ── Helpers privados ────────────────────────────────────────────

    def _ingest(self, file_bytes: bytes, file_name: str) -> DiagramFile:
        """Delega a ingestão ao value object DiagramFile."""
        try:
            return DiagramFile.create(file_bytes, file_name)
        except ValueError as e:
            raise IngestionError(str(e), step="ingestion")

    def _retrieve_rag_context(
        self,
        analysis_id: AnalysisId,
        extraction: ExtractionResult,
        log,
    ) -> RagContext:
        """Recupera contexto RAG de forma non-blocking."""
        try:
            self._vector_store.index(analysis_id, extraction)
            return self._vector_store.retrieve_context(extraction, analysis_id)
        except (RAGError, Exception) as e:
            log.warning("pipeline.rag_skipped", reason=str(e))
            return RagContext.empty()

    def _evaluate_quality(
        self,
        extraction: ExtractionResult,
        report: TechnicalReport,
        log,
    ) -> QAScore:
        """Avalia qualidade com fase determinística antes do LLM."""
        from app.domain.report.value_objects import QAScore

        # Fase 1: Verificações determinísticas (sem LLM)
        issues = self._deterministic_qa_checks(extraction, report)
        if issues:
            log.warning("qa.basic_checks_failed", issues=issues)
            return QAScore(
                is_valid=False,
                completeness_score=0.0,
                issues_found=issues,
                quality_notes="Relatório falhou nas verificações básicas de completude.",
            )

        # Fase 2: Avaliação com LLM
        return self._text_llm.evaluate_quality(extraction, report)

    def _deterministic_qa_checks(
        self,
        extraction: ExtractionResult,
        report: TechnicalReport,
    ) -> list:
        issues = []

        if not report.components_identified:
            issues.append("components_identified está vazio.")
        if not report.architectural_risks:
            issues.append("architectural_risks está vazio.")
        if not report.recommendations:
            issues.append("recommendations está vazio.")
        if len(report.executive_summary) < 100:
            issues.append(
                f"executive_summary muito curto "
                f"({len(report.executive_summary)} chars, mínimo 100)."
            )

        # Grounding: 80% dos componentes do relatório devem existir na extração
        report_set = {c.lower() for c in report.components_identified}
        source_set = {c.lower() for c in extraction.component_names}
        if source_set and report_set:
            overlap = report_set & source_set
            coverage = len(overlap) / len(report_set)
            if coverage < 0.8:
                hallucinated = report_set - source_set
                issues.append(
                    f"Componentes não encontrados na extração original: "
                    f"{', '.join(hallucinated)}"
                )

        return issues
