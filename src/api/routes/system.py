"""System health and documentation redirect routes."""

import duckdb
from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from src.api.deps import get_db_path, get_model_artifact
from src.api.schemas import HealthCheck

router = APIRouter()


@router.get("/", include_in_schema=False, tags=["System"])
def root_redirect():
    return RedirectResponse(url="/docs")


@router.get("/health", response_model=HealthCheck, tags=["System"])
def health_check():
    db_connected = False
    db_path = get_db_path()
    if db_path.exists():
        conn = None
        try:
            conn = duckdb.connect(str(db_path), read_only=True)
            conn.execute("SELECT 1").fetchone()
            db_connected = True
        except Exception:
            db_connected = False
        finally:
            if conn is not None:
                conn.close()

    model_loaded = get_model_artifact() is not None
    status = "healthy" if db_connected and model_loaded else "degraded"
    return HealthCheck(
        status=status,
        db_connected=db_connected,
        model_loaded=model_loaded,
    )
