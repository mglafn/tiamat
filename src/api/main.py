import joblib
import duckdb
import pandas as pd
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
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
            # Persistent connection is faster than opening/closing on every request
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
    description="Enterprise microservice for querying cross-vendor arbitrage spreads and XGBoost price predictions.",
    version="1.1.0",
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

# ------------------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------------------
@app.get("/health", response_model=HealthCheck, tags=["System"])
def health_check():
    """System heartbeat verifying model and database health."""
    return HealthCheck(
        status="healthy",
        db_connected=db_conn is not None,
        model_loaded=model_artifact is not None
    )

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
    # Use the global persistent connection
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
    vendor: str = Query("tcgplayer"),
    finish: str = Query("nonfoil")
):
    """Inference endpoint serving XGBoost 7-day forward price predictions."""
    if not model_artifact:
        raise HTTPException(status_code=503, detail="Forecasting model not loaded.")
    if not db_conn:
        raise HTTPException(status_code=500, detail="Database connection unavailable.")

    # Fetch latest features from warehouse
    query = """
        SELECT current_price, sma_7, sma_30, daily_return_pct
        FROM fact_training_dataset
        WHERE uuid = ? AND vendor = ? AND finish = ?
        ORDER BY price_date DESC LIMIT 1
    """
    row = db_conn.execute(query, [card_uuid, vendor, finish]).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Card metrics not found.")

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
        uuid=card_uuid, vendor=vendor, finish=finish,
        current_price=round(current_price, 2),
        predicted_7d_price=round(pred_price, 2),
        predicted_gain_pct=round(gain_pct, 2),
        model_mae=round(mae, 4)
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)