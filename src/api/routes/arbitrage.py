"""Cross-venue spatial arbitrage order-book route."""

from typing import List, Optional
import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.deps import get_db
from src.api.schemas import ArbitrageOpportunity

router = APIRouter()


@router.get("/api/v1/arbitrage", response_model=List[ArbitrageOpportunity], tags=["Analytics"])
def get_arbitrage(
    min_spread: float = Query(0.00),
    finish: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    db_conn: duckdb.DuckDBPyConnection = Depends(get_db),
):
    params = [float(min_spread)]
    finish_clause = (
        "AND f.finish = ?" if finish and finish.lower() in ["normal", "foil", "etched"] else ""
    )
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
                uuid=r[0],
                name=r[1],
                set_code=r[2],
                collector_number=str(r[3]) if r[3] else None,
                price_date=str(r[4]),
                finish=r[5],
                tcg_price=round(float(r[6]), 2),
                ck_price=round(float(r[7]), 2),
                price_spread=round(float(r[8]), 2),
                spread_pct=round(float(r[9]), 2),
            )
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Arbitrage query failed: {str(e)}")
