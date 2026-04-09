import asyncio
import json
import queue
import threading
import traceback
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager

from app.infrastructure.config.settings import get_settings
from app.shared.logging import configure_logging, get_logger
from app.infrastructure.persistence.database import get_db, check_db_connection
from app.pipeline.analysis_orchestrator import run_pipeline
from app.shared.exceptions import PipelineError

configure_logging()
logger = get_logger(__name__)

SUPPORTED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf"}

_SENTINEL = object()  # marca fim do stream


def _start_sqs_consumer():
    """Inicia o consumer SQS em thread separada (não bloqueia o servidor HTTP)."""
    settings = get_settings()
    if not settings.sqs_queue_url:
        logger.info("sqs.consumer.disabled", reason="SQS_QUEUE_URL não configurado")
        return

    from app.infrastructure.messaging.sqs_consumer import start as sqs_start

    thread = threading.Thread(target=sqs_start, daemon=True, name="sqs-consumer")
    thread.start()
    logger.info("sqs.consumer.thread_started")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ia_service.startup")
    _start_sqs_consumer()
    yield
    logger.info("ia_service.shutdown")


app = FastAPI(
    title="IA Service — Hackathon FIAP",
    description="Pipeline de análise de diagramas de arquitetura com LLM Vision e RAG.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    db_ok = check_db_connection()
    return {
        "status": "healthy" if db_ok else "degraded",
        "db": "connected" if db_ok else "unavailable",
    }


@app.post("/analyze", status_code=200)
async def analyze_diagram(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Recebe um diagrama de arquitetura (imagem ou PDF) diretamente via upload
    e executa o pipeline de análise sincronamente.
    Usado para testes — em produção o fluxo principal é via SQS.
    """
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de arquivo não suportado: .{ext}. Aceitos: {', '.join(SUPPORTED_EXTENSIONS)}",
        )

    file_bytes = await file.read()

    try:
        result = run_pipeline(
            db=db,
            file_bytes=file_bytes,
            file_name=file.filename,
        )
        return JSONResponse(status_code=200, content=result)

    except PipelineError as e:
        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:
        logger.error("analyze.unexpected_error", error=str(e))
        raise HTTPException(status_code=500, detail="Erro interno no pipeline de análise.")


@app.post("/analyze/stream")
async def analyze_diagram_stream(
    file: UploadFile = File(...),
):
    """
    Endpoint SSE — executa o pipeline e emite eventos a cada etapa.
    Formato: text/event-stream com JSON por linha.

    Nota: não usa Depends(get_db) porque o pipeline roda em thread separada
    e a sessão do FastAPI seria fechada antes do thread terminar.
    A sessão é criada dentro do thread.
    """
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de arquivo não suportado: .{ext}. Aceitos: {', '.join(SUPPORTED_EXTENSIONS)}",
        )

    file_bytes = await file.read()
    file_name = file.filename
    event_queue: queue.Queue = queue.Queue()

    def _on_step(step: str, status: str, data: dict):
        event_queue.put({"step": step, "status": status, "data": data})

    def _run():
        from app.infrastructure.persistence.database import get_session_factory
        SessionLocal = get_session_factory()
        db = SessionLocal()
        try:
            run_pipeline(
                db=db,
                file_bytes=file_bytes,
                file_name=file_name,
                on_step=_on_step,
            )
        except Exception as exc:
            event_queue.put({
                "step": "pipeline",
                "status": "error",
                "data": {
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "traceback": traceback.format_exc(),
                },
            })
        finally:
            db.close()
            event_queue.put(_SENTINEL)

    # Roda o pipeline em thread separada para não bloquear o event loop
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    async def _event_generator():
        while True:
            try:
                event = await asyncio.get_event_loop().run_in_executor(
                    None, event_queue.get, True, 300,  # timeout 5min
                )
            except queue.Empty:
                break

            if event is _SENTINEL:
                break

            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/analyses/{analysis_id}/status")
def get_status(analysis_id: str, db: Session = Depends(get_db)):
    """Consulta o status de processamento de uma análise."""
    from app.infrastructure.persistence.sqlalchemy_analysis_repository import SQLAlchemyAnalysisRepository
    from app.domain.shared.analysis_id import AnalysisId
    repo = SQLAlchemyAnalysisRepository(db)
    analysis = repo.get_by_id(AnalysisId.from_string(analysis_id))
    if not analysis:
        raise HTTPException(status_code=404, detail="Análise não encontrada.")
    return {
        "analysis_id": analysis_id,
        "status": analysis.status.value,
        "file_name": analysis.file_name,
        "error_message": analysis.error_message,
    }
