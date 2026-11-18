"""
src/api/forecast_service.py
---------------------------
Orchestrates feature-store lookup, sanitization, quantile prediction, Direct
unit economics, and Flipper defensive veto evaluation for /api/v1/forecast.
"""

import logging
from typing import Any
import duckdb
from fastapi import HTTPException
import pandas as pd

from src.analytics.inference import (
    BuyerRadarProxyFlipperRule,
    ForecastBundle,
    evaluate_direct_flip_scalar,
    predict_quantiles,
)
from src.api.schemas import PredictionResponse
from src.config import FEATURE_COLS, FEATURE_SCHEMA

logger = logging.getLogger("uvicorn.error")

ALLOWED_FEATURE_COLS = tuple(FEATURE_COLS)


def normalize_finish(finish: str) -> str:
    lowered = finish.lower()
    return "normal" if lowered in ("nonfoil", "regular") else lowered


def sanitize_features_for_inference(feature_cols: list, feature_vals: tuple) -> pd.DataFrame:
    data = dict(zip(feature_cols, feature_vals))
    df = pd.DataFrame([data])
    for col in feature_cols:
        if col in FEATURE_SCHEMA:
            target_type, default_val = FEATURE_SCHEMA[col]
            df[col] = (
                pd.to_numeric(df[col], errors="coerce").fillna(default_val).astype(target_type)
            )
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)
    return df


def compute_card_forecast(
    card_uuid: str,
    finish: str,
    is_pro: bool,
    model_artifact: Any,
    db_conn: duckdb.DuckDBPyConnection,
) -> PredictionResponse:
    if not model_artifact:
        raise HTTPException(status_code=503, detail="Forecasting model artifact not loaded.")

    bundle = (
        model_artifact
        if isinstance(model_artifact, ForecastBundle)
        else ForecastBundle.from_artifact(model_artifact)
    )
    normalized_finish = normalize_finish(finish)
    feature_cols = [c for c in bundle.feature_cols if c in ALLOWED_FEATURE_COLS]
    cols_sql = ", ".join(feature_cols)

    query = f"""
        SELECT current_price, vendor, {cols_sql} FROM fact_card_features
        WHERE uuid = ? AND finish = ? ORDER BY price_date DESC LIMIT 1
    """
    try:
        row = db_conn.cursor().execute(query, [card_uuid, normalized_finish]).fetchone()
    except Exception as e:
        logger.error(f"Error reading feature store: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error reading feature store: {str(e)}")

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Pricing metrics not found for finish '{finish}'.",
        )

    current_price = float(row[0]) if row[0] is not None else 0.0
    input_df = sanitize_features_for_inference(feature_cols, row[2:])

    preds = predict_quantiles(bundle, input_df)
    move_prob = float(preds.move_prob[0])
    predicted_gain_pct = float(preds.q50[0])
    cqr_lpb = float(preds.q10[0])
    model_mae_dollars = round(current_price * (bundle.mae_pct / 100.0), 4)

    decay_3d = (
        float(input_df["price_decay_velocity_3d"].iloc[0])
        if "price_decay_velocity_3d" in input_df
        else 0.0
    )
    amihud_val = (
        float(input_df["amihud_illiquidity_30d"].iloc[0])
        if "amihud_illiquidity_30d" in input_df
        else 0.0
    )

    flip = evaluate_direct_flip_scalar(
        current_price=current_price,
        pred_return_pct=predicted_gain_pct,
        q10_return_pct=cqr_lpb,
        amihud=amihud_val,
        is_pro=is_pro,
    )
    rule = BuyerRadarProxyFlipperRule(prob_threshold=bundle.tau_buyer_radar)
    veto_reasons = rule.veto_reasons_scalar(
        move_prob=move_prob,
        cqr_lpb=cqr_lpb,
        decay_3d=decay_3d,
        net_expected_roi_pct=flip.exp_net_roi_pct,
        basis=flip.basis,
        allocated_units=flip.allocated_units,
    )

    return PredictionResponse(
        uuid=card_uuid,
        vendor="consensus",
        finish=normalized_finish,
        current_price=round(current_price, 2),
        predicted_7d_price=flip.expected_exit_price,
        predicted_gain_pct=round(predicted_gain_pct, 2),
        model_mae=model_mae_dollars,
        move_prob=round(move_prob, 4),
        cqr_lpb=round(cqr_lpb, 2),
        price_decay_velocity_3d=round(decay_3d, 2),
        amihud_illiquidity_30d=round(amihud_val, 6),
        directional_accuracy_pct=None,
        expected_net_payout=round(flip.expected_payout, 2),
        net_expected_roi_pct=round(flip.exp_net_roi_pct, 2),
        is_dead_zone_clamped=flip.is_dead_zone_clamped,
        kappa_risk=round(flip.kappa_risk, 4),
        allocated_kelly_units=flip.allocated_units,
        is_defensive_vetoed=len(veto_reasons) > 0,
        veto_reasons=veto_reasons,
    )
