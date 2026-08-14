import joblib
import duckdb
import pandas as pd
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

# ------------------------------------------------------------------------------
# Robust Path Resolution
# ------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"
MODEL_PATH = BASE_DIR / "models" / "xgboost_forecast.joblib"

# ------------------------------------------------------------------------------
# Global State Management
# ------------------------------------------------------------------------------
model_artifact = None
db_conn = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown. 
    Maintains persistent connections to ML models and analytical databases.
    """
    global model_artifact, db_conn
    # 1. Load XGBoost Model Artifact
    if MODEL_PATH.exists():
        try:
            model_artifact = joblib.load(MODEL_PATH)
            print(f"[Startup] Successfully loaded XGBoost model from: {MODEL_PATH}")
        except Exception as e:
            print(f"[Startup Error] Model artifact load failed: {e}")
    else:
        print(f"[Startup Warning] Model artifact not found at {MODEL_PATH}")

    # 2. Establish Persistent DuckDB Connection (Read-Only)
    if DB_PATH.exists():
        try:
            db_conn = duckdb.connect(str(DB_PATH), read_only=True)
            print(f"[Startup] Persistent Read-Only connection to DuckDB established.")
        except Exception as e:
            print(f"[Startup Error] Database connection failed: {e}")
    else:
        print(f"[Startup Warning] DuckDB database not found at {DB_PATH}")

    yield  # API is now serving requests

    # 3. Shutdown: Clean up resources
    if db_conn:
        db_conn.close()
        print("[Shutdown] DuckDB connection closed.")

# ------------------------------------------------------------------------------
# Application Initialization
# ------------------------------------------------------------------------------
app = FastAPI(
    title="Financial Arbitrage & Asset Forecasting API",
    description="Enterprise microservice for querying cross-vendor arbitrage spreads, card portfolio market summaries, and XGBoost price predictions.",
    version="1.3.0",
    lifespan=lifespan
)

# ------------------------------------------------------------------------------
# Schemas (Pydantic)
# ------------------------------------------------------------------------------
class HealthCheck(BaseModel):
    status: str
    db_connected: bool
    model_loaded: bool

class ArbitrageOpportunity(BaseModel):
    uuid: str
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

class CardMarketSummary(BaseModel):
    uuid: str
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
    finish: str
    floor_price: float
    avg_price: float
    vendor_count: int
# ------------------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def root():
    """Redirects root URL requests automatically to interactive Swagger API docs."""
    return RedirectResponse(url="/docs")

@app.get("/health", response_model=HealthCheck, tags=["System"])
def health_check():
    """System heartbeat verifying model and database health."""
    return HealthCheck(
        status="healthy",
        db_connected=db_conn is not None,
        model_loaded=model_artifact is not None
    )

@app.get("/api/v1/search", response_model=List[CardSearchResult], tags=["Search"])
def search_card_by_name(
    name: str = Query(..., min_length=2, description="Partial or full card name to resolve"),
    limit: int = Query(20, le=100)
):
    """
    Resolves human-readable card names to unique system UUIDs & printing variants.
    Aggregates vendor prices to return market floor and average price per SKU.
    """
    if not db_conn:
        raise HTTPException(status_code=500, detail="Database connection unavailable.")

    # Group by UUID + Finish to eliminate duplicate printing rows
    query = """
        SELECT 
            d.uuid, 
            d.name, 
            d.set_code, 
            f.finish,
            MIN(f.current_price) as floor_price,
            AVG(f.current_price) as avg_price,
            COUNT(DISTINCT f.vendor) as vendor_count
        FROM dim_cards d
        JOIN fact_training_dataset f ON d.uuid = f.uuid
        WHERE d.name ILIKE ?
          AND f.price_date = (SELECT MAX(price_date) FROM fact_training_dataset)
        GROUP BY d.uuid, d.name, d.set_code, f.finish
        ORDER BY floor_price DESC
        LIMIT ?
    """
    search_term = f"%{name}%"
    rows = db_conn.execute(query, [search_term, limit]).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No card printings found matching '{name}'.")

    return [
        CardSearchResult(
            uuid=r[0], 
            name=r[1], 
            set_code=r[2],
            finish=r[3], 
            floor_price=round(r[4], 2),
            avg_price=round(r[5], 2),
            vendor_count=r[6]
        ) for r in rows
    ]
@app.get("/api/v1/arbitrage", response_model=List[ArbitrageOpportunity], tags=["Analytics"])
def get_arbitrage(
    min_spread: float = Query(2.00, description="Minimum dollar spread threshold"),
    limit: int = Query(50, le=500)
):
    """Retrieves real-time arbitrage spreads between TCGPlayer and CardKingdom."""
    if not db_conn:
        raise HTTPException(status_code=500, detail="Database connection unavailable.")

    query = """
        SELECT uuid, CAST(price_date AS VARCHAR), finish, tcg_price, ck_price, price_spread, spread_pct
        FROM fact_arbitrage_opportunities
        WHERE price_spread >= ?
        ORDER BY price_spread DESC
        LIMIT ?
    """
    rows = db_conn.execute(query, [min_spread, limit]).fetchall()

    return [
        ArbitrageOpportunity(
            uuid=r[0], price_date=r[1], finish=r[2],
            tcg_price=round(r[3], 2), ck_price=round(r[4], 2),
            price_spread=round(r[5], 2), spread_pct=round(r[6], 2)
        ) for r in rows
    ]

@app.get("/api/v1/forecast/{card_uuid}", response_model=PredictionResponse, tags=["Predictive"])
def get_forecast(
    card_uuid: str,
    vendor: str = Query("tcgplayer", description="Vendor name (e.g., tcgplayer, cardkingdom)"),
    finish: str = Query("normal", description="Finish type: 'normal' or 'foil'")
):
    """Inference endpoint serving XGBoost 7-day forward price predictions."""
    if not model_artifact:
        raise HTTPException(status_code=503, detail="Forecasting model not loaded.")
    if not db_conn:
        raise HTTPException(status_code=500, detail="Database connection unavailable.")

    # Schema normalization: map 'nonfoil' alias to MTGJSON's 'normal'
    normalized_finish = "normal" if finish.lower() in ["nonfoil", "regular"] else finish.lower()

    # Fetch latest features from warehouse
    query = """
        SELECT current_price, sma_7, sma_30, daily_return_pct
        FROM fact_training_dataset
        WHERE uuid = ? AND vendor = ? AND finish = ?
        ORDER BY price_date DESC LIMIT 1
    """
    row = db_conn.execute(query, [card_uuid, vendor.lower(), normalized_finish]).fetchone()

    if not row:
        raise HTTPException(
            status_code=404, 
            detail=f"Card metrics not found for vendor '{vendor}' with finish '{finish}'."
        )

    current_price, sma_7, sma_30, daily_return_pct = row

    # Prepare for inference
    input_df = pd.DataFrame([{
        'current_price': current_price,
        'sma_7': sma_7,
        'sma_30': sma_30,
        'daily_return_pct': daily_return_pct
    }])

    # Model inference
    model = model_artifact["model"]
    mae = model_artifact["metrics"].get("mae", 0.0)
    pred_price = float(model.predict(input_df)[0])
    gain_pct = ((pred_price - current_price) / current_price) * 100 if current_price > 0 else 0

    return PredictionResponse(
        uuid=card_uuid, 
        vendor=vendor, 
        finish=normalized_finish,
        current_price=round(current_price, 2),
        predicted_7d_price=round(pred_price, 2),
        predicted_gain_pct=round(gain_pct, 2),
        model_mae=round(mae, 4)
    )
@app.get("/api/v1/card/summary/{card_uuid}", response_model=CardMarketSummary, tags=["Analytics"])
def get_card_summary(card_uuid: str):
    """
    Card Portfolio Summary: Aggregates floor, ceiling, and average market prices across 
    all vendor/finish variants for a given card UUID and runs ML inference on its primary variant.
    """
    if not db_conn:
        raise HTTPException(status_code=500, detail="Database connection unavailable.")
    if not model_artifact:
        raise HTTPException(status_code=503, detail="Forecasting model not loaded.")

    date_query = "SELECT MAX(price_date) FROM fact_training_dataset WHERE uuid = ?"
    latest_date_row = db_conn.execute(date_query, [card_uuid]).fetchone()

    if not latest_date_row or not latest_date_row[0]:
        raise HTTPException(status_code=404, detail=f"No pricing records found for card UUID: {card_uuid}")

    latest_date = latest_date_row[0]

    agg_query = """
        SELECT 
            COUNT(*) as variant_count,
            MIN(current_price) as floor_price,
            AVG(current_price) as avg_price,
            MAX(current_price) as ceiling_price
        FROM fact_training_dataset
        WHERE uuid = ? AND price_date = ?
    """
    agg_row = db_conn.execute(agg_query, [card_uuid, latest_date]).fetchone()
    variant_count, floor_price, avg_price, ceiling_price = agg_row

    variant_query = """
        SELECT vendor, finish, current_price, sma_7, sma_30, daily_return_pct
        FROM fact_training_dataset
        WHERE uuid = ? AND price_date = ?
        ORDER BY current_price DESC
        LIMIT 1
    """
    v_row = db_conn.execute(variant_query, [card_uuid, latest_date]).fetchone()
    vendor, finish, current_price, sma_7, sma_30, daily_return_pct = v_row

    input_df = pd.DataFrame([{
        'current_price': current_price,
        'sma_7': sma_7,
        'sma_30': sma_30,
        'daily_return_pct': daily_return_pct
    }])

    model = model_artifact["model"]
    pred_price = float(model.predict(input_df)[0])
    gain_pct = ((pred_price - current_price) / current_price) * 100 if current_price > 0 else 0

    return CardMarketSummary(
        uuid=card_uuid,
        latest_price_date=str(latest_date),
        total_market_variants=variant_count,
        floor_price=round(floor_price, 2),
        avg_price=round(avg_price, 2),
        ceiling_price=round(ceiling_price, 2),
        primary_vendor=vendor,
        primary_finish=finish,
        predicted_7d_price=round(pred_price, 2),
        predicted_gain_pct=round(gain_pct, 2)
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)