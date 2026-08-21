import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional, Dict
from decimal import Decimal, ROUND_HALF_EVEN
import duckdb
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"
MODEL_PATH = BASE_DIR / "models" / "xgboost_forecast.joblib"

# ---------------------------------------------------------
# Custom Pickled Definitions (Required for joblib.load)
# ---------------------------------------------------------
def custom_asymmetric_objective(y_true, y_pred):
    errors = y_pred - y_true
    alpha = 0.20
    gamma = 5.0
    grad = np.where(errors > 0, 2.0 * (1.0 - alpha + gamma) * errors, 2.0 * alpha * errors)
    hess = np.where(errors > 0, 2.0 * (1.0 - alpha + gamma), 2.0 * alpha)
    return grad, hess


class ConformalizedLowerBoundGenerator:
    def __init__(self, alpha: float = 0.10):
        self.q_lo_model = GradientBoostingRegressor(loss='quantile', alpha=alpha / 2.0, n_estimators=100, random_state=42)
        self.q_hi_model = GradientBoostingRegressor(loss='quantile', alpha=1.0 - (alpha / 2.0), n_estimators=100, random_state=42)
        self.alpha = alpha
        self.q_hat_conformal = None

    def fit_and_calibrate(self, X_train, y_train, X_cal, y_cal):
        self.q_lo_model.fit(X_train, y_train)
        self.q_hi_model.fit(X_train, y_train)
        q_lo_preds = self.q_lo_model.predict(X_cal)
        q_hi_preds = self.q_hi_model.predict(X_cal)
        scores = np.maximum(q_lo_preds - y_cal.to_numpy(), y_cal.to_numpy() - q_hi_preds)
        n = len(y_cal)
        q_level = np.ceil((n + 1) * (1.0 - self.alpha)) / n
        q_level = min(1.0, max(0.0, q_level))
        self.q_hat_conformal = float(np.quantile(scores, q_level, method='higher'))

    def predict_lpb(self, X_test):
        if self.q_hat_conformal is None:
            raise ValueError("CQR model must be calibrated prior to generating lower prediction bounds.")
        raw_q_lo = self.q_lo_model.predict(X_test)
        return raw_q_lo - self.q_hat_conformal


# ---------------------------------------------------------
# Feature Store Alignment (17 Features)
# ---------------------------------------------------------
ALLOWED_FEATURE_COLS = (
    'sma_ratio', 'volatility_14d', 'daily_return_pct', 'velocity_7d_pct',
    'bid_ask_spread_pct', 'spread_velocity_7d', 'vendor_delta_7d',
    'price_decay_velocity_3d', 'amihud_illiquidity_30d',
    'is_foil', 'is_reserved', 'mana_value', 'popularity_score',
    'is_land', 'is_creature', 'asset_age_years', 'rarity_score'
)

FEATURE_SCHEMA = {
    'sma_ratio': (float, 1.0),
    'volatility_14d': (float, 0.0),
    'daily_return_pct': (float, 0.0),
    'velocity_7d_pct': (float, 0.0),
    'bid_ask_spread_pct': (float, 1.0),
    'spread_velocity_7d': (float, 0.0),
    'vendor_delta_7d': (float, 0.0),
    'price_decay_velocity_3d': (float, 0.0),
    'amihud_illiquidity_30d': (float, 0.0),
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


# ---------------------------------------------------------
# Payout & Condition Haircut Calculus
# ---------------------------------------------------------
def calculate_direct_payout(
    price: float,
    tax_rate: float = 0.075,
    clamp_dead_zone: bool = True,
    is_pro: bool = False
) -> float:
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
    safe_direct = max(0.40, direct_price)
    downgrade_penalty = (safe_direct - (salvage_factor * acq_cost)) / safe_direct
    reject_penalty = 1.0
    penalty = (downgrade_rate * max(0.0, downgrade_penalty)) + (reject_rate * reject_penalty)
    kappa_risk = 1.0 - penalty
    return float(max(0.80, min(1.00, kappa_risk)))


def sanitize_features_for_inference(feature_cols: list, feature_vals: tuple) -> pd.DataFrame:
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
            print(f"Loaded XGBoost CQR model artifact from: {MODEL_PATH}")
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
    title="Tiamat Quantitative Secondary Market Analytics & CQR Forecast API",
    description="Serves real-time spatial arbitrage spreads, DuckDB OLAP windowing, and CQR risk-gated 7-day price forecasts.",
    version="3.0.0",
    lifespan=lifespan
)

allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Pydantic Response Schemas
# ---------------------------------------------------------
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
    move_prob: float
    cqr_lpb: float
    price_decay_velocity_3d: float
    amihud_illiquidity_30d: float
    directional_accuracy_pct: Optional[float] = None
    expected_net_payout: Optional[float] = None
    net_expected_roi_pct: Optional[float] = None
    is_dead_zone_clamped: Optional[bool] = None
    kappa_risk: Optional[float] = None
    allocated_kelly_units: int = 1
    is_defensive_vetoed: bool = False
    veto_reasons: List[str] = []


class CardMarketSummary(BaseModel):
    uuid: str
    name: str = "Unknown Asset"
    set_code: str = "OTC"
    collector_number: Optional[str] = None
    edhrec_rank: Optional[int] = None
    latest_price_date: Optional[str] = None
    total_market_variants: int = 1
    floor_price: Optional[float] = None
    avg_price: Optional[float] = None
    ceiling_price: Optional[float] = None
    primary_vendor: Optional[str] = None
    primary_finish: Optional[str] = None
    predicted_7d_price: Optional[float] = None
    predicted_gain_pct: Optional[float] = None


class CardSearchResult(BaseModel):
    uuid: str
    name: str
    set_code: str
    collector_number: Optional[str] = None
    finish: str
    floor_price: float
    avg_price: float
    vendor_count: int


# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------
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


@app.get("/api/v1/backtest", tags=["Analytics"])
def get_backtest_simulation(
    hurdle: float = Query(8.0, ge=0.0, le=50.0),
    tau: Optional[float] = Query(None, ge=0.5, le=0.99),
    filter_mode: str = Query("cqr_veto", pattern="^(cqr_veto|exp_roi|win_roi|kelly)$"),
    sizing: str = Query("kelly", pattern="^(flat|kelly)$"),
    top_daily: int = Query(0, ge=0, le=20),
    is_pro: bool = Query(False)
):
    from src.analytics.backtest import run_arbitrage_backtest
    try:
        results = run_arbitrage_backtest(
            min_net_roi_pct=hurdle,
            tau=tau,
            filter_mode=filter_mode,
            sizing=sizing,
            top_daily=top_daily,
            is_pro=is_pro,
            as_dict=True
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backtest simulation failed: {str(e)}")


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
    mae_pct = metrics.get("mae_pct", 3.866)
    directional_acc = metrics.get("directional_accuracy_pct", 67.3)
    prob_threshold = metrics.get("prob_threshold", 0.90)

    classifier = model_artifact.get("classifier")
    regressor = model_artifact.get("regressor")
    cqr_generator = model_artifact.get("cqr_generator")

    # 1. Two-stage inference
    move_prob = float(classifier.predict_proba(input_df)[0][1]) if classifier else 0.0
    predicted_gain_pct = float(regressor.predict(input_df)[0]) if regressor and (move_prob >= prob_threshold) else 0.0

    # 2. CQR Lower Prediction Bound
    if cqr_generator:
        cqr_lpb = float(cqr_generator.predict_lpb(input_df)[0])
    else:
        cqr_lpb = predicted_gain_pct - 10.0

    # 3. Unit Economics & Landed Cost
    predicted_7d_price = max(0.01, round(current_price * (1.0 + (predicted_gain_pct / 100.0)), 2))
    model_mae_dollars = round(current_price * (mae_pct / 100.0), 4)

    inbound_postage = 0.99 if current_price < 5.00 else 0.15
    hub_freight = 0.012
    basis = (current_price * 1.075) + inbound_postage + hub_freight

    raw_expected_payout = calculate_direct_payout(predicted_7d_price, 0.075, clamp_dead_zone=True, is_pro=False)
    kappa_win = calculate_condition_risk_haircut(predicted_7d_price, basis)
    payout_win = raw_expected_payout * kappa_win
    profit_win = payout_win - basis

    # Downside failure state modeling (-10% drift)
    assumed_fail_price = current_price * 0.90
    raw_fail_payout = calculate_direct_payout(assumed_fail_price, 0.075, clamp_dead_zone=True, is_pro=False)
    kappa_fail = calculate_condition_risk_haircut(assumed_fail_price, basis)
    payout_fail = raw_fail_payout * kappa_fail
    profit_fail = payout_fail - basis

    exp_net_profit = (move_prob * profit_win) + ((1.0 - move_prob) * profit_fail)
    net_expected_roi_pct = (exp_net_profit / basis) * 100.0 if basis > 0 else 0.0

    # 4. Uncertainty Kelly Sizing Calculation
    decay_3d = float(input_df['price_decay_velocity_3d'].iloc[0]) if 'price_decay_velocity_3d' in input_df else 0.0
    amihud_val = float(input_df['amihud_illiquidity_30d'].iloc[0]) if 'amihud_illiquidity_30d' in input_df else 0.0

    est_downside = max(0.05, (predicted_gain_pct - cqr_lpb) / 100.0)
    est_upside = max(0.05, predicted_gain_pct / 100.0)
    f_kelly = 0.25 * (est_upside / (est_downside ** 2))
    f_kelly = min(0.05, max(0.0, f_kelly))

    dollar_kelly = f_kelly * 10000.0
    amihud_cap = 0.02 / max(amihud_val, 1e-5)
    final_dollar = min(dollar_kelly, 50.0, amihud_cap)
    allocated_units = int(max(1.0, np.floor(final_dollar / max(basis, 0.01))))

    # 5. Defensive Veto Gate Evaluation
    veto_reasons = []
    if move_prob < prob_threshold:
        veto_reasons.append(f"Insufficient Spike Probability ({move_prob:.1%} < {prob_threshold:.1%})")
    if cqr_lpb < -15.0:
        veto_reasons.append(f"CQR Statistical Floor Breach ({cqr_lpb:.1f}% < -15.0%)")
    if decay_3d < -0.5:
        veto_reasons.append(f"Active Price Decay / Falling Knife ({decay_3d:.2f}%/day < -0.50%/day)")
    if net_expected_roi_pct < 8.0:
        veto_reasons.append(f"Net ROI Below Hurdle ({net_expected_roi_pct:.1f}% < 8.0%)")

    is_clamped = True if 2.50 <= predicted_7d_price <= 2.67 else False

    return PredictionResponse(
        uuid=card_uuid,
        vendor="consensus",
        finish=normalized_finish,
        current_price=round(current_price, 2),
        predicted_7d_price=predicted_7d_price,
        predicted_gain_pct=round(predicted_gain_pct, 2),
        model_mae=model_mae_dollars,
        move_prob=round(move_prob, 4),
        cqr_lpb=round(cqr_lpb, 2),
        price_decay_velocity_3d=round(decay_3d, 2),
        amihud_illiquidity_30d=round(amihud_val, 6),
        directional_accuracy_pct=directional_acc,
        expected_net_payout=round(payout_win, 2),
        net_expected_roi_pct=round(net_expected_roi_pct, 2),
        is_dead_zone_clamped=is_clamped,
        kappa_risk=round(kappa_win, 4),
        allocated_kelly_units=allocated_units,
        is_defensive_vetoed=len(veto_reasons) > 0,
        veto_reasons=veto_reasons
    )


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


@app.get("/api/v1/card/summary/{card_uuid}", response_model=CardMarketSummary, tags=["Analytics"])
def get_card_summary(card_uuid: str, db_conn: duckdb.DuckDBPyConnection = Depends(get_db)):
    card_name, set_code, collector_number, edhrec_rank = "Unknown Asset", "OTC", None, None
    card_exists = False
    try:
        dim_query = "SELECT name, set_code, collector_number, edhrec_rank FROM dim_cards WHERE uuid = ?"
        dim_row = db_conn.cursor().execute(dim_query, [card_uuid]).fetchone()
        if dim_row:
            card_exists = True
            card_name = dim_row[0] or "Unknown Asset"
            set_code = dim_row[1] or "OTC"
            collector_number = str(dim_row[2]) if dim_row[2] else None
            edhrec_rank = int(dim_row[3]) if dim_row[3] is not None else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch card metadata: {str(e)}")

    if not card_exists:
        check_fact = db_conn.cursor().execute("SELECT 1 FROM fact_prices WHERE uuid = ? LIMIT 1", [card_uuid]).fetchone()
        if not check_fact:
            raise HTTPException(status_code=404, detail=f"Asset UUID '{card_uuid}' not found in catalog or price records.")

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
    primary_target_finish = target_finish_row[0] if target_finish_row else "normal"

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
    floor_price = round(float(agg_row[0]), 2) if agg_row and agg_row[0] is not None else None
    avg_price = round(float(agg_row[1]), 2) if agg_row and agg_row[1] is not None else None
    ceiling_price = round(float(agg_row[2]), 2) if agg_row and agg_row[2] is not None else None
    latest_date = str(agg_row[3]) if agg_row and agg_row[3] is not None else None

    return CardMarketSummary(
        uuid=card_uuid,
        name=card_name,
        set_code=set_code,
        collector_number=collector_number,
        edhrec_rank=edhrec_rank,
        latest_price_date=latest_date,
        total_market_variants=variant_count,
        floor_price=floor_price,
        avg_price=avg_price,
        ceiling_price=ceiling_price,
        primary_vendor="consensus",
        primary_finish=str(primary_target_finish)
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="127.0.0.1", port=8000, reload=True, app_dir=str(BASE_DIR))