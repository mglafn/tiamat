import os
import sys
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional
import duckdb
import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False

logger = logging.getLogger("uvicorn.error")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.config import DB_PATH, MODEL_PATH, FEATURE_COLS, FEE_CONFIG, MODEL_CONFIG
from src.pricing.fees import calculate_direct_payout, landed_basis
from src.analytics.condition import evaluate_condition_haircut
from src.analytics.sizing import calculate_position_size

ALLOWED_FEATURE_COLS = tuple(FEATURE_COLS)


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
    'z_downside_3d': (float, 0.0),
    'velocity_3d': (float, 0.0),
    'accel_3d': (float, 0.0),
    'exhaustion_ratio': (float, 0.0),
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
    
    if HAS_RICH:
        banner_grid = Table.grid(expand=True)
        banner_grid.add_column(justify="left", ratio=3)
        banner_grid.add_column(justify="right", ratio=2)
        
        title = Text()
        title.append("TIAMAT QUANT INTERFACE", style="bold cyan")
        title.append(" │ ", style="dim white")
        title.append("FastAPI Microservice Engine", style="bold white")
        title.append("\nVectorized DuckDB OLAP • Asymmetric CQR Forecaster • Spatial Order Book", style="dim italic")
        
        meta = Text()
        meta.append(f"DB Path: {DB_PATH.name}\n", style="dim cyan")
        meta.append(f"Model: {MODEL_PATH.name}  ", style="dim yellow")
        meta.append("[Active]", style="bold green")
        
        banner_grid.add_row(title, meta)
        console.print(Panel(banner_grid, box=box.ROUNDED, border_style="cyan", padding=(0, 1)))
        console.print()
    else:
        logger.info(f"Starting Tiamat Analytics Microservice (DB: {DB_PATH}, Model: {MODEL_PATH})")

    if MODEL_PATH.exists():
        try:
            logger.info("Deserializing XGBoost model artifact...")
            model_artifact = joblib.load(MODEL_PATH)
            metrics = model_artifact.get("metrics", {})
            tau = metrics.get("tau_buyer_radar", metrics.get("prob_threshold", 0.40))
            mae = metrics.get("mae_pct", 0.0)
            
            if HAS_RICH:
                diag_table = Table(box=box.ROUNDED, border_style="green", show_header=True, header_style="bold green")
                diag_table.add_column("Subsystem Artifact", style="bold white")
                diag_table.add_column("Calibration Metric", justify="right", style="cyan")
                diag_table.add_column("Online Status", justify="right", style="bold green")
                diag_table.add_row("Multi-Quantile Engine (XGBoost q10/q50/q90)", f"Median q50 MAE = {mae:.3f}%", "ONLINE")
                diag_table.add_row("Buyer Radar Calibrator (Isotonic q90)", f"Alert Threshold τ_buyer = {tau:.4f}", "CALIBRATED")
                diag_table.add_row("DuckDB Columnar Physical Layout", "ENUM Dictionary Types + Min-Max Zonemaps", "READ_ONLY ASOF")
                console.print(Panel(diag_table, title="[bold green]Predictive Subsystem Ready for Inference[/bold green]", box=box.ROUNDED))
                console.print()
            
            logger.info(f"XGBoost model successfully loaded! (tau={tau:.4f}, MAE={mae:.3f}%)")
        except Exception as e:
            logger.error(f"Error loading model artifact: {e}", exc_info=True)
            if HAS_RICH:
                console.print(f"[bold red]✖ Error loading model artifact:[/bold red] {e}")
    else:
        logger.warning(f"Model artifact not found at {MODEL_PATH}")
        if HAS_RICH:
            console.print(f"[bold yellow]⚠ Warning:[/bold yellow] Model artifact not found at {MODEL_PATH}.")
            
    yield

def get_db():
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Database file missing. Run ETL pipeline first.")
    try:
        conn = duckdb.connect(str(DB_PATH), read_only=True)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable or locked: {str(e)}"
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
    allow_origins=allowed_origins if allowed_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
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
    hurdle: float = Query(MODEL_CONFIG["DEFAULT_ROI_HURDLE_PCT"], ge=0.0, le=50.0),
    tau: Optional[float] = Query(None, ge=0.05, le=0.99),
    filter_mode: str = Query("cqr_veto", pattern="^(cqr_veto|exp_roi|win_roi)$"),
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
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backtest simulation failed: {str(e)}")

@app.get("/api/v1/forecast/{card_uuid}", response_model=PredictionResponse, tags=["Predictive"])
def get_forecast(
    card_uuid: str, finish: str = Query("normal"), is_pro: bool = Query(False),
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
        logger.error(f"Error reading feature store: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error reading feature store: {str(e)}")
        
    if not row:
        raise HTTPException(status_code=404, detail=f"Pricing metrics not found for finish '{finish}'.")
        
    current_price, active_vendor, feature_vals = float(row[0]) if row[0] is not None else 0.0, row[1], row[2:]
    input_df = sanitize_features_for_inference(feature_cols, feature_vals)

    metrics = model_artifact.get("metrics", {})
    mae_pct = metrics.get("mae_pct", 0.0)
    # PLACEHOLDER: Uses calibrated buyer spike threshold pending dedicated Flipper entry rule
    prob_threshold = metrics.get("tau_buyer_radar", metrics.get("prob_threshold", 0.40))

    q_models = model_artifact.get("quantile_models", {})
    calibrator = model_artifact.get("isotonic_calibrator")

    if q_models and calibrator and all(q in q_models for q in (0.10, 0.50, 0.90)):
        raw_q50 = q_models[0.50].predict(input_df)
        raw_q90 = np.maximum(q_models[0.90].predict(input_df), raw_q50)
        raw_q10 = np.minimum(q_models[0.10].predict(input_df), raw_q50)
        move_prob = float(calibrator.transform(raw_q90)[0])
        predicted_gain_pct = float(raw_q50[0])
        cqr_lpb = float(raw_q10[0])
    else:
        move_prob, predicted_gain_pct, cqr_lpb = 0.0, 0.0, MODEL_CONFIG["Q10_FLOOR_PCT"]

    if pd.isna(move_prob): move_prob = 0.0
    if pd.isna(predicted_gain_pct): predicted_gain_pct = 0.0
    if pd.isna(cqr_lpb): cqr_lpb = 0.0
        
    predicted_7d_price = max(0.01, round(current_price * (1.0 + (predicted_gain_pct / 100.0)), 2))
    model_mae_dollars = round(current_price * (mae_pct / 100.0), 4)
    
    default_tax = FEE_CONFIG["DEFAULT_TAX_RATE"]
    basis = landed_basis(current_price, tax_rate=default_tax, channel="direct")

    raw_expected_payout = calculate_direct_payout(
        predicted_7d_price, default_tax, clamp_dead_zone=True, is_pro=is_pro
    )
    kappa_win = float(evaluate_condition_haircut(predicted_7d_price))
    payout_win = raw_expected_payout * kappa_win
    profit_win = payout_win - basis

    exp_net_profit = profit_win
    net_expected_roi_pct = (exp_net_profit / basis) * 100.0
    decay_3d = float(input_df['price_decay_velocity_3d'].iloc[0]) if 'price_decay_velocity_3d' in input_df else 0.0
    amihud_val = float(input_df['amihud_illiquidity_30d'].iloc[0]) if 'amihud_illiquidity_30d' in input_df else 0.0

    allocated_units = int(calculate_position_size(
        expected_roi_pct=net_expected_roi_pct,
        lower_bound_return_pct=cqr_lpb,
        basis=basis,
        amihud=amihud_val,
        portfolio_equity=10000.0,
        max_position_dollars=50.0
    ))

    q10_floor = MODEL_CONFIG["Q10_FLOOR_PCT"]
    decay_floor = MODEL_CONFIG["DECAY_VELOCITY_FLOOR_PCT"]
    roi_hurdle = MODEL_CONFIG["DEFAULT_ROI_HURDLE_PCT"]
    veto_reasons = []
    if move_prob < prob_threshold:
        veto_reasons.append(f"Insufficient Spike Probability ({move_prob:.1%} < {prob_threshold:.1%})")
    if cqr_lpb < q10_floor:
        veto_reasons.append(f"Downside Floor Breach ({cqr_lpb:.1f}% < {q10_floor:.1f}%)")
    if decay_3d < decay_floor:
        veto_reasons.append(f"Active Price Decay / Falling Knife ({decay_3d:.2f}%/day < {decay_floor:.2f}%/day)")
    if net_expected_roi_pct < roi_hurdle:
        veto_reasons.append(f"Net ROI Below Hurdle ({net_expected_roi_pct:.1f}% < {roi_hurdle:.1f}%)")
    if basis > 50.0 or (allocated_units <= 0 and cqr_lpb >= q10_floor and net_expected_roi_pct > 0.0):
        veto_reasons.append("Position Exceeds Capital Ceiling ($50.00)")

    dead_zone_max = FEE_CONFIG["DIRECT_DEAD_ZONE_MAX_PRO"] if is_pro else FEE_CONFIG["DIRECT_DEAD_ZONE_MAX"]
    is_clamped = (
        FEE_CONFIG["DIRECT_DEAD_ZONE_MIN"]
        <= predicted_7d_price
        <= dead_zone_max
    )
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
        directional_accuracy_pct=None,
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
            WHERE format = 'paper' AND list_type = 'retail' AND vendor != 'cardmarket'
            QUALIFY ROW_NUMBER() OVER (PARTITION BY uuid ORDER BY price_date DESC, price ASC) = 1
        )
        SELECT
            d.uuid, d.set_code, d.collector_number, p.floor_price, d.edhrec_rank
        FROM dim_cards d
        LEFT JOIN latest_prices p ON d.uuid = p.uuid
        WHERE d.name = (SELECT name FROM target_card) AND d.is_online_only = false
        ORDER BY (d.uuid = ?) DESC, d.set_code ASC, d.collector_number ASC
        LIMIT 40
    """
    try:
        rows = db_conn.cursor().execute(query, [card_uuid, card_uuid]).fetchall()
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
            WHERE list_type = 'retail' AND format = 'paper' AND vendor != 'cardmarket'
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
            WHERE uuid = ? AND finish = ? AND format = 'paper' AND list_type = 'retail' AND vendor != 'cardmarket'
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