"""Catalog search, printings resolution, price history, and card summary routes."""

import logging
from typing import List
import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.deps import get_db
from src.api.forecast_service import normalize_finish
from src.api.schemas import (
    CardMarketSummary,
    CardSearchResult,
    CardVariant,
    CatalogCard,
    PriceHistoryPoint,
)

logger = logging.getLogger("uvicorn.error")
router = APIRouter()


@router.get("/api/v1/catalog", response_model=List[CatalogCard], tags=["Catalog"])
def get_catalog(db_conn: duckdb.DuckDBPyConnection = Depends(get_db)):
    try:
        query = (
            "SELECT uuid, name, set_code, collector_number "
            "FROM dim_cards WHERE is_online_only = false"
        )
        rows = db_conn.cursor().execute(query).fetchall()
        return [
            CatalogCard(
                uuid=r[0],
                name=r[1],
                set_code=r[2],
                collector_number=str(r[3]) if r[3] else None,
            )
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query dim_cards: {str(e)}")


@router.get(
    "/api/v1/card/printings/{card_uuid}", response_model=List[CardVariant], tags=["Catalog"]
)
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
                uuid=r[0],
                set_code=r[1],
                collector_number=str(r[2]) if r[2] else None,
                floor_price=round(float(r[3]), 2) if r[3] is not None else None,
                edhrec_rank=int(r[4]) if r[4] is not None else None,
            )
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve variants: {str(e)}")


@router.get(
    "/api/v1/card/history/{card_uuid}", response_model=List[PriceHistoryPoint], tags=["Analytics"]
)
def get_card_history(
    card_uuid: str,
    finish: str = Query("normal"),
    days: int = Query(60),
    db_conn: duckdb.DuckDBPyConnection = Depends(get_db),
):
    normalized_finish = normalize_finish(finish)
    query = """
        SELECT
            CAST(price_date AS VARCHAR) AS price_date,
            current_price, sma_7, sma_30, daily_return_pct
        FROM fact_card_features
        WHERE uuid = ? AND finish = ?
        ORDER BY price_date DESC LIMIT ?
    """
    try:
        rows = db_conn.cursor().execute(query, [card_uuid, normalized_finish, days]).fetchall()
        rows.reverse()
        return [
            PriceHistoryPoint(
                price_date=r[0],
                price=round(float(r[1]), 2),
                sma_7=round(float(r[2]), 2) if r[2] is not None else None,
                sma_30=round(float(r[3]), 2) if r[3] is not None else None,
                daily_return_pct=round(float(r[4]), 2) if r[4] is not None else None,
            )
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch price history: {str(e)}")


@router.get("/api/v1/search", response_model=List[CardSearchResult], tags=["Search"])
def search_card_by_name(
    name: str = Query(..., min_length=2),
    limit: int = Query(20, le=100),
    db_conn: duckdb.DuckDBPyConnection = Depends(get_db),
):
    query = """
        WITH latest_prices AS (
            SELECT uuid, finish, vendor, price
            FROM fact_prices
            WHERE list_type = 'retail' AND format = 'paper' AND vendor != 'cardmarket'
            QUALIFY ROW_NUMBER() OVER(
                PARTITION BY uuid, finish, vendor ORDER BY price_date DESC
            ) = 1
        )
        SELECT
            d.uuid, d.name, d.set_code, d.collector_number, p.finish,
            MIN(p.price) AS floor_price,
            AVG(p.price) AS avg_price,
            COUNT(DISTINCT p.vendor) AS vendor_count
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
                uuid=r[0],
                name=r[1],
                set_code=r[2],
                collector_number=str(r[3]) if r[3] else None,
                finish=r[4],
                floor_price=round(float(r[5]), 2),
                avg_price=round(float(r[6]), 2),
                vendor_count=int(r[7]),
            )
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search query execution failed: {str(e)}")


@router.get(
    "/api/v1/card/summary/{card_uuid}", response_model=CardMarketSummary, tags=["Analytics"]
)
def get_card_summary(card_uuid: str, db_conn: duckdb.DuckDBPyConnection = Depends(get_db)):
    card_name, set_code, collector_number, edhrec_rank = "Unknown Asset", "OTC", None, None
    card_exists = False

    try:
        dim_query = (
            "SELECT name, set_code, collector_number, edhrec_rank FROM dim_cards WHERE uuid = ?"
        )
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
        check_fact = (
            db_conn.cursor()
            .execute("SELECT 1 FROM fact_prices WHERE uuid = ? LIMIT 1", [card_uuid])
            .fetchone()
        )
        if not check_fact:
            raise HTTPException(
                status_code=404,
                detail=f"Asset UUID '{card_uuid}' not found in catalog or price records.",
            )

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
    except Exception as e:
        logger.warning("Failed to count variants for %s: %s", card_uuid, e)

    finish_query = (
        "SELECT finish FROM fact_card_features WHERE uuid = ? ORDER BY price_date DESC LIMIT 1"
    )
    target_finish_row = db_conn.cursor().execute(finish_query, [card_uuid]).fetchone()
    primary_target_finish = target_finish_row[0] if target_finish_row else "normal"

    agg_query = """
        WITH latest_vendor_prices AS (
            SELECT vendor, price AS current_price, price_date FROM fact_prices
            WHERE uuid = ? AND finish = ? AND format = 'paper'
              AND list_type = 'retail' AND vendor != 'cardmarket'
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
        primary_finish=str(primary_target_finish),
    )
