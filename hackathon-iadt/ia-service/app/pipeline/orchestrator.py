"""
Orchestrator — coordena o pipeline completo de análise de diagramas.
Pipeline: ingestion → extraction → rag → report (com riscos) → qa
"""

import json
import time
import traceback as tb_module
from typing import Callable
from sqlalchemy.orm import Session
from app.utils.logger import get_logger
from app.utils.exceptions import (
    IngestionError, ExtractionError, RiskAnalysisError,
    ReportGenerationError, QAError, RAGError,
)
from app.db import repositories as repo

from app.pipeline import (
    ingestion_agent,
    extraction_agent,
    rag_agent,
    report_agent,
    qa_agent,
)

logger = get_logger(__name__)

# Tipo do callback: (step_name, status, data_dict) -> None
StepCallback = Callable[[str, str, dict], None]


def run_pipeline(
    db: Session,
    file_bytes: bytes,
    file_name: str,
    s3_key: str = None,
    sqs_message_id: str = None,
    on_step: StepCallback | None = None,
) -> dict:
    """
    Executa o pipeline completo e persiste os resultados.

    Args:
        on_step: callback opcional chamado a cada etapa com (step, status, data).
                 Se None, apenas loga normalmente (compatível com SQS consumer).

    Returns:
        dict com analysis_id, status, report e qa_result
    """

    def _emit(step: str, status: str, data: dict | None = None):
        if on_step:
            on_step(step, status, data or {})

    # Registra a análise com status 'recebido'
    analysis_id = repo.create_analysis(
        db, file_name=file_name, file_type=file_name.rsplit(".", 1)[-1],
        s3_key=s3_key, sqs_message_id=sqs_message_id,
    )
    log = logger.bind(analysis_id=analysis_id)
    log.info("pipeline.start")

    try:
        # ── Etapa 1: Ingestion ──────────────────────────────────────
        _emit("ingestion", "running")
        t0 = time.time()
        log.info("pipeline.step", step="ingestion")
        ingestion_result = ingestion_agent.run(file_bytes, file_name)
        _emit("ingestion", "done", {
            "file_type": ingestion_result.get("file_type", ""),
            "file_size_kb": ingestion_result.get("file_size_kb", 0),
            "elapsed": round(time.time() - t0, 1),
        })

        repo.update_analysis_status(db, analysis_id, "em_processamento")

        # ── Etapa 2: Extraction ────────���────────────────────────���───
        _emit("extraction", "running")
        t0 = time.time()
        log.info("pipeline.step", step="extraction")
        extraction_result = extraction_agent.run(ingestion_result)
        repo.save_extraction_result(db, analysis_id, extraction_result)
        _emit("extraction", "done", {
            "components_count": len(extraction_result.get("components", [])),
            "relationships_count": len(extraction_result.get("relationships", [])),
            "patterns": extraction_result.get("patterns", []),
            "elapsed": round(time.time() - t0, 1),
        })

        # ── Etapa 3: RAG (não-bloqueante, skip se sem histórico) ────
        _emit("rag", "running")
        t0 = time.time()
        log.info("pipeline.step", step="rag")
        try:
            rag_result = rag_agent.run(analysis_id, extraction_result, db=db)
        except RAGError as e:
            log.warning("pipeline.rag_skipped", reason=str(e))
            rag_result = {"has_context": False, "rag_enrichment": "", "similar_analyses": []}
        _emit("rag", "done", {
            "has_context": rag_result.get("has_context", False),
            "similar_count": len(rag_result.get("similar_analyses", [])),
            "elapsed": round(time.time() - t0, 1),
        })

        # ── Etapa 4: Report (com riscos embutidos) ──────────────────
        _emit("report", "running")
        t0 = time.time()
        log.info("pipeline.step", step="report")
        report_result = report_agent.run(extraction_result, rag_result)

        risks = report_result.get("architectural_risks", [])
        severity = {
            "high": sum(1 for r in risks if r.get("severity", "").upper() == "ALTO"),
            "medium": sum(1 for r in risks if r.get("severity", "").upper() == "MÉDIO"),
            "low": sum(1 for r in risks if r.get("severity", "").upper() == "BAIXO"),
        }
        _emit("report", "done", {
            "components_count": len(report_result.get("components_identified", [])),
            "risks_count": len(risks),
            "severity": severity,
            "recommendations_count": len(report_result.get("recommendations", [])),
            "rag_used": report_result.get("rag_used", False),
            "elapsed": round(time.time() - t0, 1),
        })

        # ── Etapa 5: QA ──────��──────────────────────────────────────
        _emit("qa", "running")
        t0 = time.time()
        log.info("pipeline.step", step="qa")
        qa_result = qa_agent.run(extraction_result, report_result)

        if not qa_result.get("is_valid", False):
            raise QAError(
                f"Relatório rejeitado pelo QA: {qa_result.get('issues_found')}",
                step="qa",
                analysis_id=analysis_id,
            )

        _emit("qa", "done", {
            "is_valid": qa_result.get("is_valid", False),
            "completeness_score": qa_result.get("completeness_score", 0),
            "issues_count": len(qa_result.get("issues_found", [])),
            "elapsed": round(time.time() - t0, 1),
        })

        # Persiste relatório + QA
        repo.save_report(db, analysis_id, report_result, qa_result)
        repo.update_analysis_status(db, analysis_id, "analisado")

        log.info("pipeline.done", qa_score=qa_result.get("completeness_score"))

        result = {
            "analysis_id": analysis_id,
            "status": "analisado",
            "report": report_result,
            "qa": qa_result,
        }
        _emit("done", "complete", result)
        return result

    except (IngestionError, ExtractionError, RiskAnalysisError, ReportGenerationError) as e:
        log.error("pipeline.error", step=e.step, error=str(e))
        repo.update_analysis_status(db, analysis_id, "erro", error_message=str(e))
        _emit(e.step, "error", {"error": str(e), "error_type": type(e).__name__, "traceback": tb_module.format_exc()})
        raise

    except QAError as e:
        log.error("pipeline.qa_rejected", issues=str(e))
        repo.update_analysis_status(db, analysis_id, "erro", error_message=str(e))
        _emit("qa", "error", {"error": str(e), "error_type": type(e).__name__, "traceback": tb_module.format_exc()})
        raise

    except Exception as e:
        log.error("pipeline.unexpected_error", error=str(e))
        repo.update_analysis_status(db, analysis_id, "erro", error_message=str(e))
        _emit("pipeline", "error", {"error": str(e), "error_type": type(e).__name__, "traceback": tb_module.format_exc()})
        raise
