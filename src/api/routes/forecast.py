"""Predictive 7-day forecast endpoint."""

import duckdb
from fastapi import APIRouter, Depends, Query

from src.api.deps import get_db, get_model_artifact
from src.api.forecast_service import compute_card_forecast
from src.api.schemas import PredictionResponse

router = APIRouter()


@router.get("/api/v1/forecast/{card_uuid}", response_model=PredictionResponse, tags=["Predictive"])
def get_forecast(
    card_uuid: str,
    finish: str = Query("normal"),
    is_pro: bool = Query(False),
    db_conn: duckdb.DuckDBPyConnection = Depends(get_db),
):
    return compute_card_forecast(
        card_uuid=card_uuid,
        finish=finish,
        is_pro=is_pro,
        model_artifact=get_model_artifact(),
        db_conn=db_conn,
    )
