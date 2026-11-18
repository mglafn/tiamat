"""Holdout backtest simulation endpoint."""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from src.analytics.backtest import run_arbitrage_backtest
from src.api.deps import get_db_path, get_model_path
from src.config import MODEL_CONFIG

router = APIRouter()


@router.get("/api/v1/backtest", tags=["Analytics"])
def get_backtest_simulation(
    hurdle: float = Query(MODEL_CONFIG["DEFAULT_ROI_HURDLE_PCT"], ge=0.0, le=50.0),
    tau: Optional[float] = Query(None, ge=0.05, le=0.99),
    filter_mode: str = Query("cqr_veto", pattern="^(cqr_veto|exp_roi|win_roi)$"),
    sizing: str = Query("kelly", pattern="^(flat|kelly)$"),
    top_daily: int = Query(0, ge=0, le=20),
    is_pro: bool = Query(False),
):
    try:
        return run_arbitrage_backtest(
            min_net_roi_pct=hurdle,
            tau=tau,
            filter_mode=filter_mode,
            sizing=sizing,
            top_daily=top_daily,
            is_pro=is_pro,
            db_path=get_db_path(),
            model_path=get_model_path(),
            as_dict=True,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (AttributeError, ModuleNotFoundError, EOFError) as e:
        raise HTTPException(
            status_code=503,
            detail=f"Model artifact stale or unreadable ({e}); retrain via train_forecast.py.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backtest simulation failed: {str(e)}")
