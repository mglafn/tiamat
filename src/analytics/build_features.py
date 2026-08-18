"""
Feature engineering pipeline for MTG market time-series in DuckDB.

Constructs:
  - fact_card_features: Rolling calendar-aware technical indicators, bid/ask depth,
    and fundamental card attributes.
  - fact_training_dataset: 7d-to-14d forward return targets for model training.
  - fact_arbitrage_opportunities: Temporal ASOF alignment between Card Kingdom buylist
    and TCGplayer retail floors (with postage & store credit math).
"""

import os
import sys
from pathlib import Path
import duckdb

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"


def build_analytical_features(db_path: str):
    print(f"Building analytical feature store in DuckDB ({db_path})...")

    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"Database not found at '{db_path}'. Run ETL (load_duckdb.py) first."
        )

    conn = duckdb.connect(db_path)

    try:
        # 1. Base technicals, market depth & fundamentals
        print("-> Populating fact_card_features...")
        conn.execute("DROP TABLE IF EXISTS fact_card_features")
        conn.execute("""
            CREATE TABLE fact_card_features AS
            WITH daily_market AS (
                -- Daily consensus across paper listings
                SELECT 
                    uuid, 
                    finish, 
                    price_date,
                    MIN(CASE WHEN list_type = 'retail' THEN price END) AS market_retail,
                    MAX(CASE WHEN list_type = 'buylist' THEN price END) AS market_buylist,
                    COUNT(DISTINCT CASE WHEN list_type = 'retail' THEN vendor END) AS active_vendors
                FROM fact_prices
                WHERE format = 'paper'
                GROUP BY uuid, finish, price_date
            ),
            enriched_market AS (
                SELECT 
                    uuid, 
                    finish, 
                    price_date,
                    market_retail AS current_price,
                    active_vendors,
                    
                    -- Bid/ask spread percentage
                    ((market_retail - market_buylist) / NULLIF(market_retail, 0)) AS bid_ask_spread_pct,
                    
                    -- Calendar-aware rolling moving averages
                    AVG(market_retail) OVER (
                        PARTITION BY uuid, finish 
                        ORDER BY price_date ASC
                        RANGE BETWEEN INTERVAL 6 DAYS PRECEDING AND CURRENT ROW
                    ) AS sma_7,
                    AVG(market_retail) OVER (
                        PARTITION BY uuid, finish 
                        ORDER BY price_date ASC
                        RANGE BETWEEN INTERVAL 29 DAYS PRECEDING AND CURRENT ROW
                    ) AS sma_30,
                    
                    -- Normalized daily return scaled by calendar gap (handles weekend/crawler gaps)
                    ((market_retail - LAG(market_retail) OVER (
                        PARTITION BY uuid, finish ORDER BY price_date ASC
                    )) / NULLIF(LAG(market_retail) OVER (
                        PARTITION BY uuid, finish ORDER BY price_date ASC
                    ), 0) * 100.0) / GREATEST(1, COALESCE(DATE_DIFF('day', LAG(price_date) OVER (
                        PARTITION BY uuid, finish ORDER BY price_date ASC
                    ), price_date), 1)) AS daily_return_pct
                FROM daily_market
                WHERE market_retail IS NOT NULL
            )
            SELECT 
                e.uuid, 
                'consensus' AS vendor, 
                e.finish, 
                e.price_date, 
                e.current_price, 
                e.sma_7, 
                e.sma_30, 
                COALESCE(e.daily_return_pct, 0.0) AS daily_return_pct,
                
                -- Momentum indicators
                ((e.current_price - e.sma_7) / NULLIF(e.sma_7, 0)) * 100.0 AS velocity_7d_pct,
                (e.sma_7 / NULLIF(e.sma_30, 0)) AS sma_ratio,
                
                -- 14-day rolling return volatility
                COALESCE(STDDEV(e.daily_return_pct) OVER (
                    PARTITION BY e.uuid, e.finish 
                    ORDER BY e.price_date ASC
                    RANGE BETWEEN INTERVAL 13 DAYS PRECEDING AND CURRENT ROW
                ), 0.0) AS volatility_14d,
                
                -- Spread & vendor count dynamics
                COALESCE(e.bid_ask_spread_pct, 1.0) AS bid_ask_spread_pct,
                (COALESCE(e.bid_ask_spread_pct, 1.0) - FIRST_VALUE(COALESCE(e.bid_ask_spread_pct, 1.0)) OVER (
                    PARTITION BY e.uuid, e.finish 
                    ORDER BY e.price_date ASC
                    RANGE BETWEEN INTERVAL 7 DAYS PRECEDING AND CURRENT ROW
                )) AS spread_velocity_7d,
                (e.active_vendors - FIRST_VALUE(e.active_vendors) OVER (
                    PARTITION BY e.uuid, e.finish 
                    ORDER BY e.price_date ASC
                    RANGE BETWEEN INTERVAL 7 DAYS PRECEDING AND CURRENT ROW
                )) AS vendor_delta_7d,
                
                -- Categorical flags & domain fundamentals
                CASE WHEN e.finish IN ('foil', 'etched') THEN 1 ELSE 0 END AS is_foil,
                CASE WHEN d.is_reserved THEN 1 ELSE 0 END AS is_reserved,
                COALESCE(d.mana_value, 0.0) AS mana_value,
                
                -- Inverted EDHREC popularity rank score
                CASE 
                    WHEN d.edhrec_rank IS NOT NULL AND d.edhrec_rank > 0 
                    THEN (1.0 / LOG10(d.edhrec_rank + 1.0)) 
                    ELSE 0.0 
                END AS popularity_score,

                CASE WHEN d.card_type ILIKE '%Land%' THEN 1 ELSE 0 END AS is_land,
                CASE WHEN d.card_type ILIKE '%Creature%' THEN 1 ELSE 0 END AS is_creature,

                -- Vintage factor: years elapsed since first printing
                GREATEST(0.0, DATE_DIFF('day', COALESCE(d.original_release_date, e.price_date), e.price_date) / 365.25) AS asset_age_years,
                
                CASE 
                    WHEN d.rarity = 'mythic' THEN 4 
                    WHEN d.rarity = 'rare' THEN 3 
                    WHEN d.rarity = 'uncommon' THEN 2 
                    ELSE 1 
                END AS rarity_score
            FROM enriched_market e
            LEFT JOIN dim_cards d ON e.uuid = d.uuid;
        """)
        count_features = conn.execute("SELECT COUNT(*) FROM fact_card_features").fetchone()[0]
        print(f"  fact_card_features: {count_features:,} rows.")

        # 2. Supervised training set (7d to 14d forward target return)
        print("-> Populating fact_training_dataset...")
        conn.execute("DROP TABLE IF EXISTS fact_training_dataset")
        conn.execute("""
            CREATE TABLE fact_training_dataset AS
            WITH forward_targets AS (
                SELECT 
                    uuid, vendor, finish, price_date,
                    current_price, sma_ratio, volatility_14d, daily_return_pct, 
                    velocity_7d_pct, bid_ask_spread_pct, spread_velocity_7d, vendor_delta_7d,
                    is_foil, is_reserved, mana_value, popularity_score, is_land, is_creature,
                    asset_age_years, rarity_score,
                    
                    -- First available observation in the 7-14 day forward window
                    FIRST_VALUE(current_price IGNORE NULLS) OVER (
                        PARTITION BY uuid, vendor, finish 
                        ORDER BY price_date ASC
                        RANGE BETWEEN INTERVAL 7 DAYS FOLLOWING AND INTERVAL 14 DAYS FOLLOWING
                    ) AS future_price
                    
                FROM fact_card_features
            )
            SELECT 
                uuid, vendor, finish, price_date,
                current_price, sma_ratio, volatility_14d, daily_return_pct, 
                velocity_7d_pct, bid_ask_spread_pct, spread_velocity_7d, vendor_delta_7d,
                is_foil, is_reserved, mana_value, popularity_score, is_land, is_creature,
                asset_age_years, rarity_score,
                ROUND((((future_price - current_price) / NULLIF(current_price, 0)) * 100.0), 4) AS target_return_7d_pct
            FROM forward_targets
            WHERE future_price IS NOT NULL;
        """)
        count_train = conn.execute("SELECT COUNT(*) FROM fact_training_dataset").fetchone()[0]
        print(f"  fact_training_dataset: {count_train:,} rows.")

        # 3. Cross-vendor arbitrage spreads (ASOF aligned)
        print("-> Populating fact_arbitrage_opportunities (ASOF Join)...")
        conn.execute("DROP TABLE IF EXISTS fact_arbitrage_opportunities")
        conn.execute("""
            CREATE TABLE fact_arbitrage_opportunities AS
            WITH tcg_prices AS (
                SELECT 
                    uuid, 
                    finish, 
                    price_date, 
                    MIN(price) AS tcg_price
                FROM fact_prices
                WHERE vendor = 'tcgplayer' 
                  AND list_type = 'retail' 
                  AND format = 'paper'
                GROUP BY uuid, finish, price_date
            ),
            ck_buylist_prices AS (
                SELECT 
                    uuid, 
                    finish, 
                    price_date, 
                    MAX(price) AS ck_price
                FROM fact_prices
                WHERE vendor = 'cardkingdom' 
                  AND list_type = 'buylist' 
                  AND format = 'paper'
                GROUP BY uuid, finish, price_date
            ),
            latest_ck_offers AS (
                -- Most recent CK buylist offer within trailing 3 days
                SELECT 
                    c.uuid, 
                    c.finish, 
                    c.price_date AS ck_date, 
                    c.ck_price
                FROM ck_buylist_prices c
                WHERE c.price_date >= (
                    SELECT MAX(price_date) - INTERVAL 3 DAY FROM fact_prices WHERE format = 'paper'
                )
                QUALIFY ROW_NUMBER() OVER(
                    PARTITION BY c.uuid, c.finish 
                    ORDER BY c.price_date DESC
                ) = 1
            ),
            asof_aligned AS (
                -- Match CK offer to the nearest preceding TCG price (<= 3 days lag)
                SELECT 
                    c.uuid,
                    c.finish,
                    c.ck_date AS price_date,
                    t.price_date AS tcg_date,
                    t.tcg_price,
                    c.ck_price,
                    
                    -- Landed cost basis: TCG price + 7.5% estimated tax + postage ($0.99 for <$5, $0.15 for >=$5) + $0.09 CK batch freight
                    (t.tcg_price * 1.075 + CASE WHEN t.tcg_price < 5.00 THEN 0.99 ELSE 0.15 END + 0.09) AS total_acquisition_basis,
                    
                    -- Card Kingdom 30% store credit bonus
                    (c.ck_price * 1.30) AS ck_store_credit_payout
                FROM latest_ck_offers c
                ASOF JOIN tcg_prices t 
                    ON c.uuid = t.uuid 
                   AND c.finish = t.finish 
                   AND c.ck_date >= t.price_date
                WHERE t.tcg_price IS NOT NULL
                  AND DATE_DIFF('day', t.price_date, c.ck_date) <= 3
            )
            SELECT 
                uuid,
                price_date,
                finish,
                ROUND(tcg_price, 2) AS tcg_price,
                ROUND(ck_price, 2) AS ck_price,
                ROUND(ck_store_credit_payout - total_acquisition_basis, 2) AS price_spread,
                ROUND(((ck_store_credit_payout - total_acquisition_basis) / NULLIF(total_acquisition_basis, 0)) * 100.0, 2) AS spread_pct
            FROM asof_aligned
            WHERE ck_store_credit_payout > total_acquisition_basis;
        """)
        count_arb = conn.execute("SELECT COUNT(*) FROM fact_arbitrage_opportunities").fetchone()[0]
        print(f"  fact_arbitrage_opportunities: {count_arb:,} rows.")

        # 4. Indexes
        print("-> Rebuilding analytical indexes...")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_features_uuid_finish_date ON fact_card_features(uuid, finish, price_date);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_training_date ON fact_training_dataset(price_date);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_arb_spread ON fact_arbitrage_opportunities(price_spread DESC);")
        print("Done.")

    finally:
        conn.close()


if __name__ == "__main__":
    build_analytical_features(str(DB_PATH))