from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os

_engine = None
_SessionLocal = None


def _get_db_url() -> str:
    return (
        f"postgresql+psycopg2://{os.environ.get('POSTGRES_USER', 'hackathon')}:"
        f"{os.environ.get('POSTGRES_PASSWORD', 'hackathon123')}@"
        f"{os.environ.get('POSTGRES_HOST', 'localhost')}:"
        f"{os.environ.get('POSTGRES_PORT', '5432')}/"
        f"{os.environ.get('POSTGRES_DB', 'hackathon_db')}"
    )


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(_get_db_url(), pool_pre_ping=True, pool_size=3)
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionLocal


def get_db():
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
