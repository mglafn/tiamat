"""
src/api/main.py
---------------
FastAPI application entrypoint and compatibility exports.
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.deps import get_db, lifespan
from src.api.forecast_service import (
    ALLOWED_FEATURE_COLS,
    normalize_finish,
    sanitize_features_for_inference,
)
from src.api.routes import arbitrage, backtest, catalog, forecast, system
from src.config import BASE_DIR, DB_PATH, MODEL_PATH

model_artifact = None

app = FastAPI(
    title="Tiamat Quantitative Secondary Market Analytics & CQR Forecast API",
    description=(
        "Serves real-time spatial arbitrage spreads, DuckDB OLAP windowing, "
        "and CQR risk-gated 7-day price forecasts."
    ),
    version="3.0.0",
    lifespan=lifespan,
)

allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if allowed_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for route_module in (system, forecast, arbitrage, catalog, backtest):
    app.include_router(route_module.router)

__all__ = [
    "ALLOWED_FEATURE_COLS",
    "DB_PATH",
    "MODEL_PATH",
    "app",
    "get_db",
    "lifespan",
    "model_artifact",
    "normalize_finish",
    "sanitize_features_for_inference",
]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.main:app", host="127.0.0.1", port=8000, reload=True, app_dir=str(BASE_DIR))
