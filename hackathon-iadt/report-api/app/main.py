from fastapi import FastAPI, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager

from app.db.connection import get_db, check_db_connection
from app.db import repositories as repo
from app.utils.logger import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("report_api.startup")
    yield
    logger.info("report_api.shutdown")


app = FastAPI(
    title="Report API — Hackathon FIAP",
    description="API de consulta de relatórios gerados pelo IA Service.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health_check():
    db_ok = check_db_connection()
    return {
        "status": "healthy" if db_ok else "degraded",
        "db": "connected" if db_ok else "unavailable",
    }


@app.get("/reports/{analysis_id}")
def get_report(analysis_id: str, db: Session = Depends(get_db)):
    """Retorna o relatório de uma análise específica."""
    analysis = repo.get_analysis(db, analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Análise não encontrada.")

    report = repo.get_report_by_analysis(db, analysis_id)

    return {
        "analysis_id": analysis_id,
        "status": analysis["status"],
        "file_name": analysis["file_name"],
        "created_at": str(analysis["created_at"]),
        "report": report,
    }


@app.get("/reports")
def list_reports(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Lista os relatórios gerados, paginados."""
    reports = repo.list_reports(db, limit=limit, offset=offset)
    return {"total": len(reports), "limit": limit, "offset": offset, "items": reports}
