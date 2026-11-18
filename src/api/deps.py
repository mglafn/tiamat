"""
src/api/deps.py
---------------
Database connection dependency, startup lifespan, and runtime state lookup.
Reads DB_PATH, MODEL_PATH, and model_artifact dynamically from src.api.main
so test monkeypatches on src.api.main always take effect.
"""

from contextlib import asynccontextmanager
import logging
from pathlib import Path
import sys
from typing import Any
import duckdb
from fastapi import FastAPI, HTTPException

from src.analytics.inference import load_forecast_bundle
from src.cli.console import HAS_RICH, Panel, Table, box, console, print_banner
from src.config import DB_PATH, MODEL_PATH

logger = logging.getLogger("uvicorn.error")

_fallback_model_artifact: Any = None


def get_db_path() -> Path:
    api_main = sys.modules.get("src.api.main")
    return getattr(api_main, "DB_PATH", DB_PATH) if api_main is not None else DB_PATH


def get_model_path() -> Path:
    api_main = sys.modules.get("src.api.main")
    return getattr(api_main, "MODEL_PATH", MODEL_PATH) if api_main is not None else MODEL_PATH


def get_model_artifact() -> Any:
    api_main = sys.modules.get("src.api.main")
    if api_main is not None:
        return getattr(api_main, "model_artifact", None)
    return _fallback_model_artifact


def set_model_artifact(artifact: Any) -> None:
    global _fallback_model_artifact
    _fallback_model_artifact = artifact
    api_main = sys.modules.get("src.api.main")
    if api_main is not None:
        setattr(api_main, "model_artifact", artifact)


def _render_startup_diagnostics(tau: float, mae: float) -> None:
    if not HAS_RICH:
        return
    diag_table = Table(
        box=box.ROUNDED,
        border_style="green",
        show_header=True,
        header_style="bold green",
    )
    diag_table.add_column("Subsystem Artifact", style="bold white")
    diag_table.add_column("Calibration Metric", justify="right", style="cyan")
    diag_table.add_column("Online Status", justify="right", style="bold green")
    diag_table.add_row(
        "Multi-Quantile Engine (XGBoost q10/q50/q90)",
        f"Median q50 MAE = {mae:.3f}%",
        "ONLINE",
    )
    diag_table.add_row(
        "Buyer Radar Calibrator (Isotonic q90)",
        f"Alert Threshold τ_buyer = {tau:.4f}",
        "CALIBRATED",
    )
    diag_table.add_row(
        "DuckDB Columnar Physical Layout",
        "ENUM Dictionary Types + Min-Max Zonemaps",
        "READ_ONLY ASOF",
    )
    console.print(
        Panel(
            diag_table,
            title="[bold green]Predictive Subsystem Ready for Inference[/bold green]",
            box=box.ROUNDED,
        )
    )
    console.print()


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    db_path = get_db_path()
    model_path = get_model_path()

    if HAS_RICH:
        print_banner(
            "FastAPI Microservice Engine",
            "Vectorized DuckDB OLAP • Asymmetric CQR Forecaster • Spatial Order Book",
            [
                f"[dim cyan]DB Path: {db_path.name}[/dim cyan]",
                f"[dim yellow]Model: {model_path.name}[/dim yellow]  "
                "[bold green][Active][/bold green]",
            ],
            brand="TIAMAT QUANT INTERFACE",
        )
    else:
        logger.info(f"Starting Tiamat Analytics Microservice (DB: {db_path}, Model: {model_path})")

    if model_path.exists():
        try:
            logger.info("Deserializing XGBoost model artifact...")
            bundle = load_forecast_bundle(model_path)
            set_model_artifact(bundle)
            tau = bundle.tau_buyer_radar
            mae = bundle.mae_pct
            _render_startup_diagnostics(tau, mae)
            logger.info(f"XGBoost model successfully loaded! (tau={tau:.4f}, MAE={mae:.3f}%)")
        except Exception as e:
            logger.error(f"Error loading model artifact: {e}", exc_info=True)
            if HAS_RICH:
                console.print(f"[bold red]✖ Error loading model artifact:[/bold red] {e}")
    else:
        logger.warning(f"Model artifact not found at {model_path}")
        if HAS_RICH:
            console.print(
                f"[bold yellow]⚠ Warning:[/bold yellow] Model artifact not found at {model_path}."
            )

    yield


def get_db():
    db_path = get_db_path()
    if not db_path.exists():
        raise HTTPException(
            status_code=503, detail="Database file missing. Run ETL pipeline first."
        )
    try:
        conn = duckdb.connect(str(db_path), read_only=True)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable or locked: {str(e)}")
    try:
        yield conn
    finally:
        conn.close()
