import uuid
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ============================================================
# Analyses repository
# ============================================================

def create_analysis(db: Session, file_name: str, file_type: str, s3_key: str = None, sqs_message_id: str = None) -> str:
    analysis_id = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO analyses (id, status, file_name, file_type, s3_key, sqs_message_id)
            VALUES (:id, 'recebido', :file_name, :file_type, :s3_key, :sqs_message_id)
        """),
        {"id": analysis_id, "file_name": file_name, "file_type": file_type,
         "s3_key": s3_key, "sqs_message_id": sqs_message_id},
    )
    db.commit()
    logger.info("analysis.created", analysis_id=analysis_id)
    return analysis_id


def update_analysis_status(db: Session, analysis_id: str, status: str, error_message: str = None) -> None:
    db.execute(
        text("""
            UPDATE analyses
            SET status = :status, error_message = :error_message
            WHERE id = :id
        """),
        {"id": analysis_id, "status": status, "error_message": error_message},
    )
    db.commit()
    logger.info("analysis.status_updated", analysis_id=analysis_id, status=status)


def get_analysis(db: Session, analysis_id: str) -> dict | None:
    row = db.execute(
        text("SELECT * FROM analyses WHERE id = :id"),
        {"id": analysis_id},
    ).mappings().first()
    return dict(row) if row else None


# ============================================================
# Extraction results repository
# ============================================================

def save_extraction_result(db: Session, analysis_id: str, extraction: dict) -> str:
    result_id = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO extraction_results (id, analysis_id, components, relationships, patterns, raw_description)
            VALUES (:id, :analysis_id, :components, :relationships, :patterns, :raw_description)
        """),
        {
            "id": result_id,
            "analysis_id": analysis_id,
            "components": json.dumps(extraction.get("components", []), ensure_ascii=False),
            "relationships": json.dumps(extraction.get("relationships", []), ensure_ascii=False),
            "patterns": json.dumps(extraction.get("patterns", []), ensure_ascii=False),
            "raw_description": extraction.get("raw_description", ""),
        },
    )
    db.commit()
    return result_id


# ============================================================
# Reports repository
# ============================================================

def save_report(db: Session, analysis_id: str, report: dict, qa_result: dict = None) -> str:
    report_id = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO reports (
                id, analysis_id, components_identified, architectural_risks,
                recommendations, executive_summary, rag_used,
                qa_is_valid, qa_completeness_score, qa_issues_found, qa_quality_notes
            ) VALUES (
                :id, :analysis_id, :components_identified, :architectural_risks,
                :recommendations, :executive_summary, :rag_used,
                :qa_is_valid, :qa_completeness_score, :qa_issues_found, :qa_quality_notes
            )
        """),
        {
            "id": report_id,
            "analysis_id": analysis_id,
            "components_identified": json.dumps(report.get("components_identified", []), ensure_ascii=False),
            "architectural_risks": json.dumps(report.get("architectural_risks", []), ensure_ascii=False),
            "recommendations": json.dumps(report.get("recommendations", []), ensure_ascii=False),
            "executive_summary": report.get("executive_summary", ""),
            "rag_used": report.get("rag_used", False),
            "qa_is_valid": qa_result.get("is_valid") if qa_result else None,
            "qa_completeness_score": qa_result.get("completeness_score") if qa_result else None,
            "qa_issues_found": json.dumps(qa_result.get("issues_found", []), ensure_ascii=False) if qa_result else None,
            "qa_quality_notes": qa_result.get("quality_notes") if qa_result else None,
        },
    )
    db.commit()
    logger.info("report.saved", report_id=report_id, analysis_id=analysis_id)
    return report_id


def get_analysis_by_sqs_message_id(db: Session, sqs_message_id: str) -> dict | None:
    """Retorna a análise já existente para um sqs_message_id (idempotência)."""
    row = db.execute(
        text("SELECT id, status FROM analyses WHERE sqs_message_id = :msg_id LIMIT 1"),
        {"msg_id": sqs_message_id},
    ).mappings().first()
    return dict(row) if row else None


def get_report_by_analysis(db: Session, analysis_id: str) -> dict | None:
    row = db.execute(
        text("SELECT * FROM reports WHERE analysis_id = :id ORDER BY created_at DESC LIMIT 1"),
        {"id": analysis_id},
    ).mappings().first()
    return dict(row) if row else None


def list_reports(db: Session, limit: int = 20, offset: int = 0) -> list[dict]:
    rows = db.execute(
        text("""
            SELECT r.*, a.status, a.file_name, a.created_at as analysis_created_at
            FROM reports r
            JOIN analyses a ON r.analysis_id = a.id
            ORDER BY r.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"limit": limit, "offset": offset},
    ).mappings().all()
    return [dict(r) for r in rows]
