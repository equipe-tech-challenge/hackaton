"""
Orchestrator — coordena o pipeline completo de análise de diagramas.
Pipeline: ingestion → extraction → rag → risk → report → qa
"""

import json
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
    risk_agent,
    report_agent,
    qa_agent,
)

logger = get_logger(__name__)


def run_pipeline(
    db: Session,
    file_bytes: bytes,
    file_name: str,
    s3_key: str = None,
    sqs_message_id: str = None,
) -> dict:
    """
    Executa o pipeline completo e persiste os resultados.

    Returns:
        dict com analysis_id, status, report e qa_result
    """
    # Registra a análise com status 'recebido'
    analysis_id = repo.create_analysis(
        db, file_name=file_name, file_type=file_name.rsplit(".", 1)[-1],
        s3_key=s3_key, sqs_message_id=sqs_message_id,
    )
    log = logger.bind(analysis_id=analysis_id)
    log.info("pipeline.start")

    try:
        # ── Etapa 1: Ingestion ──────────────────────────────────────
        log.info("pipeline.step", step="ingestion")
        ingestion_result = ingestion_agent.run(file_bytes, file_name)

        repo.update_analysis_status(db, analysis_id, "em_processamento")

        # ── Etapa 2: Extraction ─────────────────────────────────────
        log.info("pipeline.step", step="extraction")
        extraction_result = extraction_agent.run(ingestion_result)
        repo.save_extraction_result(db, analysis_id, extraction_result)

        # ── Etapa 3: RAG (não-bloqueante) ───────────────────────────
        log.info("pipeline.step", step="rag")
        try:
            rag_result = rag_agent.run(analysis_id, extraction_result)
        except RAGError as e:
            log.warning("pipeline.rag_skipped", reason=str(e))
            rag_result = {"has_context": False, "rag_enrichment": "", "similar_analyses": []}

        # ── Etapa 4: Risk ───────────────────────────────────────────
        log.info("pipeline.step", step="risk")
        risk_result = risk_agent.run(extraction_result, rag_result)

        # ── Etapa 5: Report ─────────────────────────────────────────
        log.info("pipeline.step", step="report")
        report_result = report_agent.run(extraction_result, risk_result, rag_result)

        # ── Etapa 6: QA ─────────────────────────────────────────────
        log.info("pipeline.step", step="qa")
        qa_result = qa_agent.run(extraction_result, report_result)

        if not qa_result.get("is_valid", False):
            raise QAError(
                f"Relatório rejeitado pelo QA: {qa_result.get('issues_found')}",
                step="qa",
                analysis_id=analysis_id,
            )

        # Persiste relatório + QA
        repo.save_report(db, analysis_id, report_result, qa_result)
        repo.update_analysis_status(db, analysis_id, "analisado")

        log.info("pipeline.done", qa_score=qa_result.get("completeness_score"))

        return {
            "analysis_id": analysis_id,
            "status": "analisado",
            "report": report_result,
            "qa": qa_result,
        }

    except (IngestionError, ExtractionError, RiskAnalysisError, ReportGenerationError) as e:
        log.error("pipeline.error", step=e.step, error=str(e))
        repo.update_analysis_status(db, analysis_id, "erro", error_message=str(e))
        raise

    except QAError as e:
        log.error("pipeline.qa_rejected", issues=str(e))
        repo.update_analysis_status(db, analysis_id, "erro", error_message=str(e))
        raise

    except Exception as e:
        log.error("pipeline.unexpected_error", error=str(e))
        repo.update_analysis_status(db, analysis_id, "erro", error_message=str(e))
        raise
