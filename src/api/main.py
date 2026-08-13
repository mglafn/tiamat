import joblib
import duckdb
import pandas as pd
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

# ------------------------------------------------------------------------------
# Robust Path Resolution (Anchored to Project Root)
# ------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"
MODEL_PATH = BASE_DIR / "models" / "xgboost_forecast.joblib"

# Global state in-memory artifact
model_artifact = None


# ------------------------------------------------------------------------------
# FastAPI Lifespan Context Manager (Modern Startup/Shutdown Handling)
# ------------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages application lifecycle events. Loads the trained XGBoost model
    into memory on startup and handles clean shutdown.
    """
    global model_artifact
    if MODEL_PATH.exists():
        try:
            model_artifact = joblib.load(MODEL_PATH)
            print(f"[Startup] Successfully loaded XGBoost model from: {MODEL_PATH}")
        except Exception as e:
            print(f"[Startup Error] Failed to load model artifact: {e}")
    else:
        print(f"[Startup Warning] Model file not found at {MODEL_PATH}. Prediction endpoints will be disabled.")
    
    yield  # Application runs while suspended here
    
    print("[Shutdown] Cleaning up API resources...")


# ------------------------------------------------------------------------------
# Application Initialization
# ------------------------------------------------------------------------------
app = FastAPI(
    title="Financial Arbitrage & Asset Forecasting API",
    description="Enterprise microservice for querying cross-vendor secondary market arbitrage spreads and XGBoost forward price predictions.",
    version="1.0.0",
    lifespan=lifespan
)


# ------------------------------------------------------------------------------
# Response & Data Schemas
# ------------------------------------------------------------------------------
class HealthCheckResponse(BaseModel):
    status: str
    database_connected: bool
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
    sma_7: float
    sma_30: float
    predicted_7d_price: float
    predicted_gain_pct: float


# ------------------------------------------------------------------------------
# API Endpoints
# ------------------------------------------------------------------------------

@app.get("/health", response_model=HealthCheckResponse, tags=["Health & System"])
def health_check():
    """
    Verifies that the microservice, persistent database, and ML models are healthy.
    """
    db_status = DB_PATH.exists()
    return HealthCheckResponse(
        status="healthy",
        database_connected=db_status,
        model_loaded=model_artifact is not None
    )


@app.get(
    "/api/v1/arbitrage", 
    response_model=List[ArbitrageOpportunity], 
    tags=["Arbitrage Analytics"]
)
def get_arbitrage_opportunities(
    min_spread: float = Query(2.00, ge=0.50, description="Minimum dollar price spread between vendors"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of records to return")
):
    """
    Queries DuckDB for real-time cross-vendor price discrepancies (e.g., TCGPlayer vs CardKingdom) 
    where the spread exceeds the requested threshold.
    """
    if not DB_PATH.exists():
        raise HTTPException(status_code=500, detail="Database file not initialized. Run ETL pipelines first.")

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        query = """
            SELECT 
                uuid, 
                CAST(price_date AS VARCHAR) as price_date, 
                finish, 
                tcg_price, 
                ck_price, 
                price_spread, 
                spread_pct
            FROM fact_arbitrage_opportunities
            WHERE price_spread >= ?
            ORDER BY price_spread DESC
            LIMIT ?
        """
        results = conn.execute(query, [min_spread, limit]).fetchall()
    finally:
        conn.close()

    output = []
    for row in results:
        output.append(ArbitrageOpportunity(
            uuid=row[0],
            price_date=str(row[1]),
            finish=row[2],
            tcg_price=round(row[3], 2),
            ck_price=round(row[4], 2),
            price_spread=round(row[5], 2),
            spread_pct=round(row[6], 2)
        ))
    
    return output


@app.get(
    "/api/v1/forecast/{card_uuid}", 
    response_model=PredictionResponse, 
    tags=["Predictive Analytics"]
)
def forecast_card_price(
    card_uuid: str, 
    vendor: str = Query("tcgplayer", description="Target vendor marketplace"), 
    finish: str = Query("nonfoil", description="Card printing finish (nonfoil/foil/etched)")
):
    """
    Retrieves latest financial metrics for a card and runs XGBoost inference 
    to predict 7-day forward price movement.
    """
    if not model_artifact:
        raise HTTPException(
            status_code=503, 
            detail="ML Forecasting model unavailable. Train model first via src/analytics/train_forecast.py."
        )
    
    if not DB_PATH.exists():
        raise HTTPException(status_code=500, detail="Database file not initialized.")

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        query = """
            SELECT current_price, sma_7, sma_30, daily_return_pct
            FROM fact_training_dataset
            WHERE uuid = ? AND vendor = ? AND finish = ?
            ORDER BY price_date DESC
            LIMIT 1
        """
        row = conn.execute(query, [card_uuid, vendor, finish]).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(
            status_code=404, 
            detail=f"Card metrics for UUID '{card_uuid}' ({vendor}/{finish}) not found in data warehouse."
        )

    current_price, sma_7, sma_30, daily_return_pct = row

    # Construct input dataframe matching exact feature names used during model training
    features_df = pd.DataFrame([{
        'current_price': current_price,
        'sma_7': sma_7,
        'sma_30': sma_30,
        'daily_return_pct': daily_return_pct
    }])

    # Execute XGBoost inference
    model = model_artifact["model"]
    pred_price = float(model.predict(features_df)[0])
    
    # Calculate percentage growth forecast
    gain_pct = ((pred_price - current_price) / current_price) * 100 if current_price > 0 else 0.0

    return PredictionResponse(
        uuid=card_uuid,
        vendor=vendor,
        finish=finish,
        current_price=round(current_price, 2),
        sma_7=round(sma_7, 2),
        sma_30=round(sma_30, 2),
        predicted_7d_price=round(pred_price, 2),
        predicted_gain_pct=round(gain_pct, 2)
    )


# ------------------------------------------------------------------------------
# Entrypoint for direct script execution
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)