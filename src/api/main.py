import os
import joblib
import duckdb
import pandas as pd
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
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
    Maintains persistent connections to ML models and analytical databases.
    """
    global model_artifact, db_conn
    
    if MODEL_PATH.exists():
        try:
            model_artifact = joblib.load(MODEL_PATH)
            print(f"[Startup] Successfully loaded XGBoost model from: {MODEL_PATH}")
        except Exception as e:
            print(f"[Startup Error] Model artifact load failed: {e}")
    else:
        print(f"[Startup Warning] Model artifact not found at {MODEL_PATH}")

    if DB_PATH.exists():
        try:
            db_conn = duckdb.connect(str(DB_PATH), read_only=True)
            print("[Startup] Persistent Read-Only connection to DuckDB established.")
        except Exception as e:
            print(f"[Startup Error] Database connection failed: {e}")
    else:
        print(f"[Startup Warning] DuckDB database not found at {DB_PATH}")

    yield

    if db_conn:
        db_conn.close()
        print("[Shutdown] DuckDB connection closed.")


# ------------------------------------------------------------------------------
# Application Initialization
# ------------------------------------------------------------------------------
app = FastAPI(
    title="Financial Arbitrage & Asset Forecasting API",
    description="Enterprise microservice serving cross-vendor arbitrage spreads, historical price series, and XGBoost price forecasts.",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------------------
# Schemas (Pydantic)
# ------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", response_model=HealthCheck, tags=["System"])
def health_check():
    return HealthCheck(
        status="healthy" if (db_conn is not None and model_artifact is not None) else "degraded",
        db_connected=db_conn is not None,
        model_loaded=model_artifact is not None
    )


@app.get("/api/v1/catalog", response_model=List[CatalogCard], tags=["Catalog"])
def get_catalog():
    if not db_conn:
        raise HTTPException(status_code=503, detail="Database connection unavailable.")
    try:
        query = "SELECT uuid, name, set_code, collector_number FROM dim_cards"
        rows = db_conn.cursor().execute(query).fetchall()
        return [
            CatalogCard(
                uuid=r[0], 
                name=r[1], 
                set_code=r[2], 
                collector_number=str(r[3]) if r[3] else None
            ) for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query dim_cards: {str(e)}")


@app.get("/api/v1/card/printings/{card_uuid}", response_model=List[CardVariant], tags=["Catalog"])
def get_card_printings(card_uuid: str):
    if not db_conn:
        raise HTTPException(status_code=503, detail="Database connection unavailable.")
    
    query = """
        WITH target_card AS (
            SELECT name FROM dim_cards WHERE uuid = ?
        ),
        latest_prices AS (
            SELECT uuid, MIN(price) AS floor_price
            FROM fact_prices
            WHERE price_date = (SELECT MAX(price_date) FROM fact_prices)
              AND format = 'paper'
            GROUP BY uuid
        )
        SELECT 
            d.uuid, 
            d.set_code, 
            d.collector_number,
            p.floor_price,
            d.edhrec_rank
        FROM dim_cards d
        LEFT JOIN latest_prices p ON d.uuid = p.uuid
        WHERE d.name = (SELECT name FROM target_card)
        ORDER BY d.set_code ASC, d.collector_number ASC
        LIMIT 40
    """
    try:
        rows = db_conn.cursor().execute(query, [card_uuid]).fetchall()
        return [
            CardVariant(
                uuid=r[0], 
                set_code=r[1], 
                collector_number=str(r[2]) if r[2] else None,
                floor_price=round(float(r[3]), 2) if r[3] is not None else None,
                edhrec_rank=int(r[4]) if r[4] is not None else None
            ) for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve variants: {str(e)}")


@app.get("/api/v1/card/history/{card_uuid}", response_model=List[PriceHistoryPoint], tags=["Analytics"])
def get_card_history(
    card_uuid: str,
    vendor: str = Query("tcgplayer", description="Vendor name (e.g. tcgplayer, cardkingdom)"),
    finish: str = Query("normal", description="Finish type: 'normal' or 'foil'"),
    days: int = Query(60, ge=7, le=365, description="Number of historical trading days")
):
    """
    Returns verified historical daily prices, SMA-7, SMA-30, and daily returns.
    """
    if not db_conn:
        raise HTTPException(status_code=503, detail="Database connection unavailable.")
    
    normalized_finish = "normal" if finish.lower() in ["nonfoil", "regular"] else finish.lower()

    query = """
        SELECT 
            CAST(price_date AS VARCHAR) AS price_date,
            current_price,
            sma_7,
            sma_30,
            daily_return_pct
        FROM fact_card_features
        WHERE uuid = ? 
          AND vendor = ? 
          AND finish = ?
        ORDER BY price_date DESC
        LIMIT ?
    """
    try:
        rows = db_conn.cursor().execute(query, [card_uuid, vendor.lower(), normalized_finish, days]).fetchall()
        if not rows:
            # Fallback securely to the most prominent single vendor if requested vendor is missing
            fallback_query = """
                SELECT 
                    CAST(price_date AS VARCHAR) AS price_date,
                    current_price,
                    sma_7,
                    sma_30,
                    daily_return_pct
                FROM fact_card_features
                WHERE uuid = ? 
                  AND finish = ?
                  AND vendor = (
                      SELECT vendor 
                      FROM fact_card_features 
                      WHERE uuid = ? AND finish = ? 
                      ORDER BY price_date DESC LIMIT 1
                  )
                ORDER BY price_date DESC
                LIMIT ?
            """
            rows = db_conn.cursor().execute(
                fallback_query, 
                [card_uuid, normalized_finish, card_uuid, normalized_finish, days]
            ).fetchall()

        # Return chronologically ascending (oldest to newest) for charting
        rows.reverse()
        return [
            PriceHistoryPoint(
                price_date=r[0],
                price=round(float(r[1]), 2),
                sma_7=round(float(r[2]), 2) if r[2] is not None else None,
                sma_30=round(float(r[3]), 2) if r[3] is not None else None,
                daily_return_pct=round(float(r[4]), 2) if r[4] is not None else None
            ) for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch price history: {str(e)}")


@app.get("/api/v1/search", response_model=List[CardSearchResult], tags=["Search"])
def search_card_by_name(
    name: str = Query(..., min_length=2, description="Partial or full card name to resolve"),
    limit: int = Query(20, le=100)
):
    if not db_conn:
        raise HTTPException(status_code=503, detail="Database connection unavailable.")
    
    query = """
        SELECT 
            d.uuid, 
            d.name, 
            d.set_code, 
            d.collector_number,
            f.finish,
            MIN(f.current_price) AS floor_price,
            AVG(f.current_price) AS avg_price,
            COUNT(DISTINCT f.vendor) AS vendor_count
        FROM dim_cards d
        JOIN fact_card_features f ON d.uuid = f.uuid
        WHERE d.name ILIKE ?
          AND f.price_date = (SELECT MAX(price_date) FROM fact_card_features)
        GROUP BY d.uuid, d.name, d.set_code, d.collector_number, f.finish
        ORDER BY floor_price DESC
        LIMIT ?
    """
    try:
        search_term = f"%{name}%"
        rows = db_conn.cursor().execute(query, [search_term, limit]).fetchall()
        return [
            CardSearchResult(
                uuid=r[0], 
                name=r[1], 
                set_code=r[2], 
                collector_number=str(r[3]) if r[3] else None,
                finish=r[4], 
                floor_price=round(float(r[5]), 2),
                avg_price=round(float(r[6]), 2),
                vendor_count=int(r[7])
            ) for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search query execution failed: {str(e)}")


@app.get("/api/v1/arbitrage", response_model=List[ArbitrageOpportunity], tags=["Analytics"])
def get_arbitrage(
    min_spread: float = Query(0.00, description="Minimum dollar spread threshold"),
    limit: int = Query(100, le=500)
):
    if not db_conn:
        raise HTTPException(status_code=503, detail="Database connection unavailable.")
    
    query = """
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
        WHERE f.price_spread >= ?
        ORDER BY f.price_spread DESC
        LIMIT ?
    """
    try:
        rows = db_conn.cursor().execute(query, [float(min_spread), int(limit)]).fetchall()
        return [
            ArbitrageOpportunity(
                uuid=r[0], 
                name=r[1], 
                set_code=r[2], 
                collector_number=str(r[3]) if r[3] else None,
                price_date=str(r[4]), 
                finish=r[5], 
                tcg_price=round(float(r[6]), 2), 
                ck_price=round(float(r[7]), 2), 
                price_spread=round(float(r[8]), 2), 
                spread_pct=round(float(r[9]), 2)
            ) for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Arbitrage query failed: {str(e)}")


@app.get("/api/v1/forecast/{card_uuid}", response_model=PredictionResponse, tags=["Predictive"])
def get_forecast(
    card_uuid: str,
    vendor: str = Query("tcgplayer", description="Vendor name (e.g., tcgplayer, cardkingdom)"),
    finish: str = Query("normal", description="Finish type: 'normal' or 'foil'")
):
    if not model_artifact:
        raise HTTPException(status_code=503, detail="Forecasting model artifact not loaded.")
    if not db_conn:
        raise HTTPException(status_code=503, detail="Database connection unavailable.")

    normalized_finish = "normal" if finish.lower() in ["nonfoil", "regular"] else finish.lower()
    feature_cols = model_artifact.get("feature_cols", [
        'sma_ratio', 'volatility_14d', 'daily_return_pct', 'velocity_7d_pct',
        'is_foil', 'rarity_score', 'edhrec_rank'
    ])
    cols_sql = ", ".join(feature_cols)

    query = f"""
        SELECT current_price, {cols_sql}
        FROM fact_card_features
        WHERE uuid = ? AND vendor = ? AND finish = ?
        ORDER BY price_date DESC LIMIT 1
    """
    try:
        row = db_conn.cursor().execute(query, [card_uuid, vendor.lower(), normalized_finish]).fetchone()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading feature store: {str(e)}")

    if not row:
        raise HTTPException(
            status_code=404, 
            detail=f"Card pricing metrics not found for vendor '{vendor}' and finish '{finish}'."
        )

    current_price = float(row[0])
    feature_vals = row[1:]

    input_df = pd.DataFrame([dict(zip(feature_cols, feature_vals))]).fillna(0.0)

    model = model_artifact["model"]
    metrics = model_artifact.get("metrics", {})
    mae_pct = metrics.get("mae_pct", 5.0)
    directional_acc = metrics.get("directional_accuracy_pct", None)

    # Predict relative 7-day return %
    predicted_gain_pct = float(model.predict(input_df)[0])
    predicted_7d_price = current_price * (1.0 + (predicted_gain_pct / 100.0))
    predicted_7d_price = max(0.01, round(predicted_7d_price, 2))

    # Convert percentage MAE to dollar uncertainty at this asset's price point
    model_mae_dollars = round(current_price * (mae_pct / 100.0), 4)

    return PredictionResponse(
        uuid=card_uuid, 
        vendor=vendor, 
        finish=normalized_finish,
        current_price=round(current_price, 2),
        predicted_7d_price=predicted_7d_price,
        predicted_gain_pct=round(predicted_gain_pct, 2),
        model_mae=model_mae_dollars,
        directional_accuracy_pct=directional_acc
    )


@app.get("/api/v1/card/summary/{card_uuid}", response_model=CardMarketSummary, tags=["Analytics"])
def get_card_summary(card_uuid: str):
    if not db_conn:
        raise HTTPException(status_code=503, detail="Database connection unavailable.")
    if not model_artifact:
        raise HTTPException(status_code=503, detail="Forecasting model not loaded.")

    card_name = "Unknown Asset"
    set_code = "OTC"
    collector_number = None
    edhrec_rank = None

    try:
        dim_query = "SELECT name, set_code, collector_number, edhrec_rank FROM dim_cards WHERE uuid = ?"
        dim_row = db_conn.cursor().execute(dim_query, [card_uuid]).fetchone()
        if dim_row:
            card_name = dim_row[0]
            set_code = dim_row[1]
            collector_number = str(dim_row[2]) if dim_row[2] else None
            edhrec_rank = int(dim_row[3]) if dim_row[3] is not None else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch card metadata: {str(e)}")

    date_query = "SELECT MAX(price_date) FROM fact_card_features WHERE uuid = ?"
    latest_date_row = db_conn.cursor().execute(date_query, [card_uuid]).fetchone()
    if not latest_date_row or not latest_date_row[0]:
        raise HTTPException(status_code=404, detail=f"No pricing records found for card UUID: {card_uuid}")
    
    latest_date = latest_date_row[0]

    agg_query = """
        SELECT 
            COUNT(*) AS variant_count,
            MIN(current_price) AS floor_price,
            AVG(current_price) AS avg_price,
            MAX(current_price) AS ceiling_price
        FROM fact_card_features
        WHERE uuid = ? AND price_date = ?
    """
    agg_row = db_conn.cursor().execute(agg_query, [card_uuid, latest_date]).fetchone()
    variant_count, floor_price, avg_price, ceiling_price = agg_row

    feature_cols = model_artifact.get("feature_cols", [
        'sma_ratio', 'volatility_14d', 'daily_return_pct', 'velocity_7d_pct',
        'is_foil', 'rarity_score', 'edhrec_rank'
    ])
    cols_sql = ", ".join(feature_cols)

    variant_query = f"""
        SELECT vendor, finish, current_price, {cols_sql}
        FROM fact_card_features
        WHERE uuid = ? AND price_date = ?
        ORDER BY current_price DESC
        LIMIT 1
    """
    v_row = db_conn.cursor().execute(variant_query, [card_uuid, latest_date]).fetchone()
    if not v_row:
        raise HTTPException(status_code=404, detail=f"Variant pricing not found for card UUID: {card_uuid}")

    vendor, finish = v_row[0], v_row[1]
    current_price = float(v_row[2])
    feature_vals = v_row[3:]

    input_df = pd.DataFrame([dict(zip(feature_cols, feature_vals))]).fillna(0.0)
    model = model_artifact["model"]

    pred_return_pct = float(model.predict(input_df)[0])
    pred_price = max(0.01, round(current_price * (1.0 + (pred_return_pct / 100.0)), 2))

    return CardMarketSummary(
        uuid=card_uuid,
        name=card_name,
        set_code=set_code,
        collector_number=collector_number,
        edhrec_rank=edhrec_rank,
        latest_price_date=str(latest_date),
        total_market_variants=int(variant_count),
        floor_price=round(float(floor_price), 2),
        avg_price=round(float(avg_price), 2),
        ceiling_price=round(float(ceiling_price), 2),
        primary_vendor=str(vendor),
        primary_finish=str(finish),
        predicted_7d_price=pred_price,
        predicted_gain_pct=round(pred_return_pct, 2)
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="127.0.0.1", port=8000, reload=True, app_dir=str(BASE_DIR))