from sqlalchemy.orm import Session
from sqlalchemy import text


def get_analysis(db: Session, analysis_id: str) -> dict | None:
    row = db.execute(
        text("SELECT * FROM analyses WHERE id = :id"),
        {"id": analysis_id},
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
