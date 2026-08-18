"""
REST microservice for cross-vendor arbitrage spreads and forward XGBoost predictions.
"""

import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional
from decimal import Decimal, ROUND_HALF_EVEN
import duckdb
import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"
MODEL_PATH = BASE_DIR / "models" / "xgboost_forecast.joblib"

ALLOWED_FEATURE_COLS = (
    'sma_ratio', 'volatility_14d', 'daily_return_pct', 'velocity_7d_pct',
    'bid_ask_spread_pct', 'spread_velocity_7d', 'vendor_delta_7d',
    'is_foil', 'is_reserved', 'mana_value', 'popularity_score',
    'is_land', 'is_creature', 'asset_age_years', 'rarity_score'
)

# Explicit schema mapping for inference payloads to avoid XGBoost dtype mismatch panics
FEATURE_SCHEMA = {
    'sma_ratio': (float, 1.0),
    'volatility_14d': (float, 0.0),
    'daily_return_pct': (float, 0.0),
    'velocity_7d_pct': (float, 0.0),
    'bid_ask_spread_pct': (float, 1.0),
    'spread_velocity_7d': (float, 0.0),
    'vendor_delta_7d': (float, 0.0),
    'is_foil': (int, 0),
    'is_reserved': (int, 0),
    'mana_value': (float, 0.0),
    'popularity_score': (float, 0.0),
    'is_land': (int, 0),
    'is_creature': (int, 0),
    'asset_age_years': (float, 0.0),
    'rarity_score': (int, 1)
}

model_artifact = None


def calculate_direct_payout(
    price: float, 
    tax_rate: float = 0.075, 
    clamp_dead_zone: bool = True, 
    is_pro: bool = False
) -> float:
    """
    Computes exact net seller payout under TCGplayer Direct rate rules using Banker's rounding.

    Rules:
      - P < $0.40: Ineligible ($0.00).
      - $0.40 <= P <= $2.49: 50% flat fee (commissions/processing waived).
      - $2.50 <= P <= $2.67: Dead zone; clamping to $2.49 yields higher net payout.
      - P >= $2.50: $1.12 flat + 8.95% commission (cap $75) + 2.5% processing on gross with tax.
    """
    d_price = Decimal(str(round(price, 4)))
    d_tax = Decimal(str(tax_rate))

    if d_price < Decimal('0.40'):
        return 0.0

    if clamp_dead_zone and Decimal('2.50') <= d_price <= Decimal('2.67'):
        d_price = Decimal('2.49')

    if d_price < Decimal('2.50'):
        fee = (d_price * Decimal('0.50')).quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)
        return float(d_price - fee)

    direct_fixed = Decimal('1.12')
    commission = min(d_price * Decimal('0.0895'), Decimal('75.00'))
    pro_fee = min(d_price * Decimal('0.025'), Decimal('75.00')) if is_pro else Decimal('0.00')
    
    gross_total = d_price * (Decimal('1.00') + d_tax)
    processing_fee = gross_total * Decimal('0.025')

    total_fee = (direct_fixed + commission + pro_fee + processing_fee).quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)
    payout = max(Decimal('0.00'), d_price - total_fee)
    return float(payout.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN))


def calculate_condition_risk_haircut(
    direct_price: float,
    acq_cost: float,
    downgrade_rate: float = 0.035,
    reject_rate: float = 0.005,
    salvage_factor: float = 0.75
) -> float:
    """
    Calculates condition downgrade haircut (kappa_risk) for Louisville intake.
    Models replacement debit risk and SEI inventory salvage recovery.
    """
    safe_direct = max(0.40, direct_price)
    downgrade_penalty = (safe_direct - (salvage_factor * acq_cost)) / safe_direct
    reject_penalty = 1.0

    penalty = (downgrade_rate * max(0.0, downgrade_penalty)) + (reject_rate * reject_penalty)
    kappa_risk = 1.0 - penalty
    return float(max(0.80, min(1.00, kappa_risk)))


def sanitize_features_for_inference(feature_cols: list, feature_vals: tuple) -> pd.DataFrame:
    """
    Enforces expected data types and schema defaults before passing to XGBoost.
    """
    data = dict(zip(feature_cols, feature_vals))
    df = pd.DataFrame([data])

    for col in feature_cols:
        if col in FEATURE_SCHEMA:
            target_type, default_val = FEATURE_SCHEMA[col]
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(default_val).astype(target_type)
        else:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0).astype(float)

    return df


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model_artifact
    if MODEL_PATH.exists():
        try:
            model_artifact = joblib.load(MODEL_PATH)
            print(f"Loaded XGBoost model artifact from: {MODEL_PATH}")
        except Exception as e:
            print(f"Error loading model artifact: {e}")
    else:
        print(f"Warning: Model artifact not found at {MODEL_PATH}")
    yield


def get_db():
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Database file missing. Run ETL pipeline first.")
    try:
        conn = duckdb.connect(str(DB_PATH), read_only=True)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable or locked by an active ETL job: {str(e)}"
        )
    try:
        yield conn
    finally:
        conn.close()


app = FastAPI(
    title="MTG Financial Arbitrage & Forecasting API",
    description="Serves real-time cross-vendor arbitrage spreads, historical price series, and 7-day XGBoost price forecasts.",
    version="2.4.1",
    lifespan=lifespan
)

# CORS whitelist
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class HealthCheck(BaseModel):
    status: str
    db_connected: bool
    model_loaded: bool


class CatalogCard(BaseModel):
    uuid: str
    name: str
    set_code: str
    collector_number: Optional[str] = None


class CardVariant(BaseModel):
    uuid: str
    set_code: str
    collector_number: Optional[str] = None
    floor_price: Optional[float] = None
    edhrec_rank: Optional[int] = None


class PriceHistoryPoint(BaseModel):
    price_date: str
    price: float
    sma_7: Optional[float] = None
    sma_30: Optional[float] = None
    daily_return_pct: Optional[float] = None


class ArbitrageOpportunity(BaseModel):
    uuid: str
    name: Optional[str] = "Unknown Asset"
    set_code: Optional[str] = "OTC"
    collector_number: Optional[str] = None
    price_date: str
    finish: str
    tcg_price: float
    ck_price: float
    price_spread: float
    spread_pct: float


class PredictionResponse(BaseModel):
    uuid: str
    vendor: str
    finish: str
    current_price: float
    predicted_7d_price: float
    predicted_gain_pct: float
    model_mae: float
    directional_accuracy_pct: Optional[float] = None
    expected_net_payout: Optional[float] = None
    net_expected_roi_pct: Optional[float] = None
    is_dead_zone_clamped: Optional[bool] = None
    kappa_risk: Optional[float] = None


class CardMarketSummary(BaseModel):
    uuid: str
    name: str = "Unknown Asset"
    set_code: str = "OTC"
    collector_number: Optional[str] = None
    edhrec_rank: Optional[int] = None
    latest_price_date: str
    total_market_variants: int
    floor_price: float
    avg_price: float
    ceiling_price: float
    primary_vendor: str
    primary_finish: str
    predicted_7d_price: float
    predicted_gain_pct: float


class CardSearchResult(BaseModel):
    uuid: str
    name: str
    set_code: str
    collector_number: Optional[str] = None
    finish: str
    floor_price: float
    avg_price: float
    vendor_count: int


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", response_model=HealthCheck, tags=["System"])
def health_check():
    db_alive = False
    if DB_PATH.exists():
        try:
            test_conn = duckdb.connect(str(DB_PATH), read_only=True)
            test_conn.execute("SELECT 1").fetchone()
            test_conn.close()
            db_alive = True
        except Exception:
            db_alive = False

    return HealthCheck(
        status="healthy" if (db_alive and model_artifact is not None) else "degraded",
        db_connected=db_alive,
        model_loaded=model_artifact is not None
    )


@app.get("/api/v1/catalog", response_model=List[CatalogCard], tags=["Catalog"])
def get_catalog(db_conn: duckdb.DuckDBPyConnection = Depends(get_db)):
    try:
        query = "SELECT uuid, name, set_code, collector_number FROM dim_cards WHERE is_online_only = false"
        rows = db_conn.cursor().execute(query).fetchall()
        return [
            CatalogCard(
                uuid=r[0], name=r[1], set_code=r[2], collector_number=str(r[3]) if r[3] else None
            ) for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query dim_cards: {str(e)}")


@app.get("/api/v1/card/printings/{card_uuid}", response_model=List[CardVariant], tags=["Catalog"])
def get_card_printings(card_uuid: str, db_conn: duckdb.DuckDBPyConnection = Depends(get_db)):
    query = """
        WITH target_card AS (
            SELECT name FROM dim_cards WHERE uuid = ?
        ),
        latest_prices AS (
            SELECT uuid, price AS floor_price
            FROM fact_prices
            WHERE format = 'paper' AND list_type = 'retail'
            QUALIFY ROW_NUMBER() OVER (PARTITION BY uuid ORDER BY price_date DESC, price ASC) = 1
        )
        SELECT 
            d.uuid, d.set_code, d.collector_number, p.floor_price, d.edhrec_rank
        FROM dim_cards d
        LEFT JOIN latest_prices p ON d.uuid = p.uuid
        WHERE d.name = (SELECT name FROM target_card) AND d.is_online_only = false
        ORDER BY d.set_code ASC, d.collector_number ASC
        LIMIT 40
    """
    try:
        rows = db_conn.cursor().execute(query, [card_uuid]).fetchall()
        return [
            CardVariant(
                uuid=r[0], set_code=r[1], collector_number=str(r[2]) if r[2] else None,
                floor_price=round(float(r[3]), 2) if r[3] is not None else None,
                edhrec_rank=int(r[4]) if r[4] is not None else None
            ) for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve variants: {str(e)}")


@app.get("/api/v1/card/history/{card_uuid}", response_model=List[PriceHistoryPoint], tags=["Analytics"])
def get_card_history(
    card_uuid: str, finish: str = Query("normal"), days: int = Query(60),
    db_conn: duckdb.DuckDBPyConnection = Depends(get_db)
):
    normalized_finish = "normal" if finish.lower() in ["nonfoil", "regular"] else finish.lower()
    query = """
        SELECT CAST(price_date AS VARCHAR) AS price_date, current_price, sma_7, sma_30, daily_return_pct
        FROM fact_card_features
        WHERE uuid = ? AND finish = ?
        ORDER BY price_date DESC LIMIT ?
    """
    try:
        rows = db_conn.cursor().execute(query, [card_uuid, normalized_finish, days]).fetchall()
        rows.reverse()
        return [
            PriceHistoryPoint(
                price_date=r[0], price=round(float(r[1]), 2),
                sma_7=round(float(r[2]), 2) if r[2] is not None else None,
                sma_30=round(float(r[3]), 2) if r[3] is not None else None,
                daily_return_pct=round(float(r[4]), 2) if r[4] is not None else None
            ) for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch price history: {str(e)}")


@app.get("/api/v1/search", response_model=List[CardSearchResult], tags=["Search"])
def search_card_by_name(
    name: str = Query(..., min_length=2), limit: int = Query(20, le=100),
    db_conn: duckdb.DuckDBPyConnection = Depends(get_db)
):
    query = """
        WITH latest_prices AS (
            SELECT uuid, finish, vendor, price
            FROM fact_prices
            WHERE list_type = 'retail' AND format = 'paper'
            QUALIFY ROW_NUMBER() OVER(PARTITION BY uuid, finish, vendor ORDER BY price_date DESC) = 1
        )
        SELECT 
            d.uuid, d.name, d.set_code, d.collector_number, p.finish,
            MIN(p.price) AS floor_price, AVG(p.price) AS avg_price, COUNT(DISTINCT p.vendor) AS vendor_count
        FROM dim_cards d
        JOIN latest_prices p ON d.uuid = p.uuid
        WHERE d.name ILIKE ? AND d.is_online_only = false
        GROUP BY d.uuid, d.name, d.set_code, d.collector_number, p.finish
        ORDER BY floor_price DESC
        LIMIT ?
    """
    try:
        rows = db_conn.cursor().execute(query, [f"%{name}%", limit]).fetchall()
        return [
            CardSearchResult(
                uuid=r[0], name=r[1], set_code=r[2], collector_number=str(r[3]) if r[3] else None,
                finish=r[4], floor_price=round(float(r[5]), 2), avg_price=round(float(r[6]), 2), vendor_count=int(r[7])
            ) for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search query execution failed: {str(e)}")


@app.get("/api/v1/arbitrage", response_model=List[ArbitrageOpportunity], tags=["Analytics"])
def get_arbitrage(
    min_spread: float = Query(0.00), finish: Optional[str] = Query(None), limit: int = Query(100, le=500),
    db_conn: duckdb.DuckDBPyConnection = Depends(get_db)
):
    params = [float(min_spread)]
    finish_clause = "AND f.finish = ?" if finish and finish.lower() in ["normal", "foil", "etched"] else ""
    if finish_clause:
        params.append(finish.lower())
    params.append(int(limit))

    query = f"""
        SELECT 
            f.uuid, 
            COALESCE(d.name, f.uuid) AS name, 
            COALESCE(d.set_code, 'OTC') AS set_code,
            d.collector_number, 
            CAST(f.price_date AS VARCHAR) AS price_date, 
            f.finish, 
            f.tcg_price, 
            f.ck_price, 
            f.price_spread, 
            f.spread_pct
        FROM fact_arbitrage_opportunities f
        LEFT JOIN dim_cards d ON f.uuid = d.uuid
        WHERE f.price_spread >= ? {finish_clause}
        ORDER BY f.price_spread DESC LIMIT ?
    """
    try:
        rows = db_conn.cursor().execute(query, params).fetchall()
        return [
            ArbitrageOpportunity(
                uuid=r[0], name=r[1], set_code=r[2], collector_number=str(r[3]) if r[3] else None,
                price_date=str(r[4]), finish=r[5], tcg_price=round(float(r[6]), 2), 
                ck_price=round(float(r[7]), 2), price_spread=round(float(r[8]), 2), spread_pct=round(float(r[9]), 2)
            ) for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Arbitrage query failed: {str(e)}")


@app.get("/api/v1/forecast/{card_uuid}", response_model=PredictionResponse, tags=["Predictive"])
def get_forecast(
    card_uuid: str, finish: str = Query("normal"),
    db_conn: duckdb.DuckDBPyConnection = Depends(get_db)
):
    if not model_artifact:
        raise HTTPException(status_code=503, detail="Forecasting model artifact not loaded.")

    normalized_finish = "normal" if finish.lower() in ["nonfoil", "regular"] else finish.lower()
    raw_cols = model_artifact.get("feature_cols", list(ALLOWED_FEATURE_COLS))
    feature_cols = [c for c in raw_cols if c in ALLOWED_FEATURE_COLS]
    cols_sql = ", ".join(feature_cols)

    query = f"""
        SELECT current_price, vendor, {cols_sql} FROM fact_card_features
        WHERE uuid = ? AND finish = ? ORDER BY price_date DESC LIMIT 1
    """
    try:
        row = db_conn.cursor().execute(query, [card_uuid, normalized_finish]).fetchone()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading feature store: {str(e)}")

    if not row:
        raise HTTPException(status_code=404, detail=f"Pricing metrics not found for finish '{finish}'.")

    current_price, active_vendor, feature_vals = float(row[0]), row[1], row[2:]
    input_df = sanitize_features_for_inference(feature_cols, feature_vals)

    metrics = model_artifact.get("metrics", {})
    mae_pct = metrics.get("mae_pct", 5.0)
    directional_acc = metrics.get("directional_accuracy_pct", None)

    classifier = model_artifact.get("classifier")
    regressor = model_artifact.get("regressor")

    if classifier and regressor:
        prob_threshold = metrics.get("prob_threshold", 0.5)
        move_prob = float(classifier.predict_proba(input_df)[0][1])
        predicted_gain_pct = float(regressor.predict(input_df)[0]) if move_prob >= prob_threshold else 0.0
    else:
        model = model_artifact["model"]
        predicted_gain_pct = float(model.predict(input_df)[0])

    predicted_7d_price = max(0.01, round(current_price * (1.0 + (predicted_gain_pct / 100.0)), 2))
    model_mae_dollars = round(current_price * (mae_pct / 100.0), 4)

    inbound_postage = 0.99 if current_price < 5.00 else 0.15
    hub_freight = 0.012
    acquisition_cost = (current_price * 1.075) + inbound_postage + hub_freight
    
    # Net direct payout & condition risk adjustment (kappa_risk)
    raw_expected_payout = calculate_direct_payout(predicted_7d_price, 0.075, clamp_dead_zone=True, is_pro=False)
    kappa_risk = calculate_condition_risk_haircut(predicted_7d_price, acquisition_cost)
    expected_net_payout = raw_expected_payout * kappa_risk
    
    net_expected_roi_pct = ((expected_net_payout - acquisition_cost) / acquisition_cost) * 100.0 if acquisition_cost > 0 else 0.0
    is_clamped = True if 2.50 <= predicted_7d_price <= 2.67 else False

    return PredictionResponse(
        uuid=card_uuid, vendor="consensus", finish=normalized_finish,
        current_price=round(current_price, 2), predicted_7d_price=predicted_7d_price,
        predicted_gain_pct=round(predicted_gain_pct, 2), model_mae=model_mae_dollars,
        directional_accuracy_pct=directional_acc, expected_net_payout=round(expected_net_payout, 2),
        net_expected_roi_pct=round(net_expected_roi_pct, 2), is_dead_zone_clamped=is_clamped,
        kappa_risk=round(kappa_risk, 4)
    )


@app.get("/api/v1/card/summary/{card_uuid}", response_model=CardMarketSummary, tags=["Analytics"])
def get_card_summary(card_uuid: str, db_conn: duckdb.DuckDBPyConnection = Depends(get_db)):
    if not model_artifact:
        raise HTTPException(status_code=503, detail="Forecasting model not loaded.")

    card_name, set_code, collector_number, edhrec_rank = "Unknown Asset", "OTC", None, None
    try:
        dim_query = "SELECT name, set_code, collector_number, edhrec_rank FROM dim_cards WHERE uuid = ?"
        dim_row = db_conn.cursor().execute(dim_query, [card_uuid]).fetchone()
        if dim_row:
            card_name, set_code = dim_row[0], dim_row[1]
            collector_number = str(dim_row[2]) if dim_row[2] else None
            edhrec_rank = int(dim_row[3]) if dim_row[3] is not None else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch card metadata: {str(e)}")

    variant_count = 1
    try:
        var_query = """
            SELECT COUNT(DISTINCT d2.uuid) FROM dim_cards d1
            JOIN dim_cards d2 ON d1.name = d2.name
            WHERE d1.uuid = ? AND d2.is_online_only = false
        """
        var_res = db_conn.cursor().execute(var_query, [card_uuid]).fetchone()
        if var_res and var_res[0]:
            variant_count = int(var_res[0])
    except Exception:
        pass

    finish_query = "SELECT finish FROM fact_card_features WHERE uuid = ? ORDER BY price_date DESC LIMIT 1"
    target_finish_row = db_conn.cursor().execute(finish_query, [card_uuid]).fetchone()
    if not target_finish_row:
        raise HTTPException(status_code=404, detail=f"No pricing records found for card UUID: {card_uuid}")

    primary_target_finish = target_finish_row[0]
    agg_query = """
        WITH latest_vendor_prices AS (
            SELECT vendor, price as current_price, price_date FROM fact_prices
            WHERE uuid = ? AND finish = ? AND format = 'paper' AND list_type = 'retail'
            QUALIFY ROW_NUMBER() OVER (PARTITION BY vendor ORDER BY price_date DESC) = 1
        )
        SELECT MIN(current_price), AVG(current_price), MAX(current_price), MAX(price_date)
        FROM latest_vendor_prices
    """
    agg_row = db_conn.cursor().execute(agg_query, [card_uuid, primary_target_finish]).fetchone()
    if not agg_row or agg_row[0] is None:
        raise HTTPException(status_code=404, detail=f"Pricing not found for card UUID: {card_uuid}")
    floor_price, avg_price, ceiling_price, latest_date = agg_row

    raw_cols = model_artifact.get("feature_cols", list(ALLOWED_FEATURE_COLS))
    feature_cols = [c for c in raw_cols if c in ALLOWED_FEATURE_COLS]
    cols_sql = ", ".join(feature_cols)

    feature_query = f"""
        SELECT current_price, {cols_sql} FROM fact_card_features
        WHERE uuid = ? AND finish = ?
        ORDER BY price_date DESC LIMIT 1
    """
    f_row = db_conn.cursor().execute(feature_query, [card_uuid, primary_target_finish]).fetchone()
    if not f_row:
        raise HTTPException(status_code=404, detail=f"Variant features not found for card UUID: {card_uuid}")

    current_price, feature_vals = float(f_row[0]), f_row[1:]

    vendor_query = """
        WITH latest_vendor_prices AS (
            SELECT vendor, price as current_price FROM fact_prices
            WHERE uuid = ? AND finish = ? AND format = 'paper' AND list_type = 'retail'
            QUALIFY ROW_NUMBER() OVER (PARTITION BY vendor ORDER BY price_date DESC) = 1
        )
        SELECT vendor FROM latest_vendor_prices ORDER BY ABS(current_price - ?) ASC LIMIT 1
    """
    v_row = db_conn.cursor().execute(vendor_query, [card_uuid, primary_target_finish, avg_price]).fetchone()
    vendor = v_row[0] if v_row else "consensus"
    finish = primary_target_finish

    input_df = sanitize_features_for_inference(feature_cols, feature_vals)

    metrics = model_artifact.get("metrics", {})
    classifier = model_artifact.get("classifier")
    regressor = model_artifact.get("regressor")

    if classifier and regressor:
        prob_threshold = metrics.get("prob_threshold", 0.5)
        move_prob = float(classifier.predict_proba(input_df)[0][1])
        pred_return_pct = float(regressor.predict(input_df)[0]) if move_prob >= prob_threshold else 0.0
    else:
        model = model_artifact["model"]
        pred_return_pct = float(model.predict(input_df)[0])

    pred_price = max(0.01, round(current_price * (1.0 + (pred_return_pct / 100.0)), 2))

    return CardMarketSummary(
        uuid=card_uuid, name=card_name, set_code=set_code, collector_number=collector_number,
        edhrec_rank=edhrec_rank, latest_price_date=str(latest_date), total_market_variants=variant_count,
        floor_price=round(float(floor_price), 2), avg_price=round(float(avg_price), 2),
        ceiling_price=round(float(ceiling_price), 2), primary_vendor=str(vendor),
        primary_finish=str(finish), predicted_7d_price=pred_price, predicted_gain_pct=round(pred_return_pct, 2)
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="127.0.0.1", port=8000, reload=True, app_dir=str(BASE_DIR))