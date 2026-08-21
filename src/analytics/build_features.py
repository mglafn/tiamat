# src/analytics/build_features.py
import os
import sys
from pathlib import Path
import duckdb

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"

def build_analytical_features(db_path: str):
    if not Path(db_path).exists():
        raise FileNotFoundError(f"Database not found at '{db_path}'. Run ETL (load_duckdb.py) first.")

    conn = duckdb.connect(db_path, config={
        'threads': '2',
        'preserve_insertion_order': 'false'
    })
    try:
        conn.execute("DROP TABLE IF EXISTS fact_card_features")
        conn.execute("""
            CREATE TABLE fact_card_features AS
            WITH daily_market AS (
                SELECT
                    uuid,
                    finish,
                    price_date,
                    MIN(CASE WHEN list_type = 'retail' THEN price END) AS market_retail,
                    MAX(CASE WHEN list_type = 'buylist' THEN price END) AS market_buylist,
                    COUNT(CASE WHEN list_type = 'retail' THEN 1 END) AS active_vendors
                FROM fact_prices
                WHERE format = 'paper'
                GROUP BY uuid, finish, price_date
                HAVING MIN(CASE WHEN list_type = 'retail' THEN price END) IS NOT NULL
            ),
            enriched_market AS (
                SELECT
                    uuid,
                    finish,
                    price_date,
                    market_retail AS current_price,
                    active_vendors,
                    COALESCE((market_retail - market_buylist) / NULLIF(market_retail, 0), 1.0) AS bid_ask_spread_pct,
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
                    COALESCE(((market_retail - LAG(market_retail) OVER (
                        PARTITION BY uuid, finish ORDER BY price_date ASC
                    )) / NULLIF(LAG(market_retail) OVER (
                        PARTITION BY uuid, finish ORDER BY price_date ASC
                    ), 0) * 100.0) / GREATEST(1, COALESCE(DATE_DIFF('day', LAG(price_date) OVER (
                        PARTITION BY uuid, finish ORDER BY price_date ASC
                    ), price_date), 1)), 0.0) AS daily_return_pct,
                    LAG(market_retail, 3) OVER (
                        PARTITION BY uuid, finish ORDER BY price_date ASC
                    ) AS price_t_minus_3
                FROM daily_market
            )
            SELECT
                e.uuid,
                'consensus' AS vendor,
                e.finish,
                e.price_date,
                e.current_price,
                e.sma_7,
                e.sma_30,
                e.daily_return_pct,
                ((e.current_price - e.sma_7) / NULLIF(e.sma_7, 0)) * 100.0 AS velocity_7d_pct,
                (e.sma_7 / NULLIF(e.sma_30, 0)) AS sma_ratio,
                COALESCE(STDDEV(e.daily_return_pct) OVER (
                    PARTITION BY e.uuid, e.finish
                    ORDER BY e.price_date ASC
                    RANGE BETWEEN INTERVAL 13 DAYS PRECEDING AND CURRENT ROW
                ), 0.0) AS volatility_14d,
                e.bid_ask_spread_pct,
                (e.bid_ask_spread_pct - FIRST_VALUE(e.bid_ask_spread_pct) OVER (
                    PARTITION BY e.uuid, e.finish
                    ORDER BY e.price_date ASC
                    RANGE BETWEEN INTERVAL 7 DAYS PRECEDING AND CURRENT ROW
                )) AS spread_velocity_7d,
                (e.active_vendors - FIRST_VALUE(e.active_vendors) OVER (
                    PARTITION BY e.uuid, e.finish
                    ORDER BY e.price_date ASC
                    RANGE BETWEEN INTERVAL 7 DAYS PRECEDING AND CURRENT ROW
                )) AS vendor_delta_7d,
                COALESCE(((e.current_price - e.price_t_minus_3) / NULLIF(e.price_t_minus_3, 0) / 3.0) * 100.0, 0.0) AS price_decay_velocity_3d,
                AVG(ABS(e.daily_return_pct) / NULLIF(e.current_price * e.active_vendors, 0)) OVER (
                    PARTITION BY e.uuid, e.finish
                    ORDER BY e.price_date ASC
                    RANGE BETWEEN INTERVAL 29 DAYS PRECEDING AND CURRENT ROW
                ) AS amihud_illiquidity_30d,
                CASE WHEN e.finish IN ('foil', 'etched') THEN 1 ELSE 0 END AS is_foil,
                CASE WHEN d.is_reserved THEN 1 ELSE 0 END AS is_reserved,
                COALESCE(d.mana_value, 0.0) AS mana_value,
                CASE
                    WHEN d.edhrec_rank IS NOT NULL AND d.edhrec_rank > 0
                    THEN (1.0 / LOG10(d.edhrec_rank + 1.0))
                    ELSE 0.0
                END AS popularity_score,
                CASE WHEN d.card_type ILIKE '%Land%' THEN 1 ELSE 0 END AS is_land,
                CASE WHEN d.card_type ILIKE '%Creature%' THEN 1 ELSE 0 END AS is_creature,
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

        conn.execute("DROP TABLE IF EXISTS fact_training_dataset")
        conn.execute("""
            CREATE TABLE fact_training_dataset AS
            WITH forward_targets AS (
                SELECT
                    uuid, vendor, finish, price_date,
                    current_price, sma_ratio, volatility_14d, daily_return_pct,
                    velocity_7d_pct, bid_ask_spread_pct, spread_velocity_7d, vendor_delta_7d,
                    price_decay_velocity_3d, amihud_illiquidity_30d,
                    is_foil, is_reserved, mana_value, popularity_score, is_land, is_creature,
                    asset_age_years, rarity_score,
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
                price_decay_velocity_3d, amihud_illiquidity_30d,
                is_foil, is_reserved, mana_value, popularity_score, is_land, is_creature,
                asset_age_years, rarity_score,
                ROUND((((future_price - current_price) / NULLIF(current_price, 0)) * 100.0), 4) AS target_return_7d_pct
            FROM forward_targets
            WHERE future_price IS NOT NULL;
        """)

        conn.execute("DROP TABLE IF EXISTS fact_arbitrage_opportunities")
        conn.execute("""
            CREATE TABLE fact_arbitrage_opportunities AS
            WITH tcg_prices AS (
                SELECT uuid, finish, price_date, MIN(price) AS tcg_price
                FROM fact_prices
                WHERE vendor = 'tcgplayer' AND list_type = 'retail' AND format = 'paper'
                GROUP BY uuid, finish, price_date
            ),
            ck_buylist_prices AS (
                SELECT uuid, finish, price_date, MAX(price) AS ck_price
                FROM fact_prices
                WHERE vendor = 'cardkingdom' AND list_type = 'buylist' AND format = 'paper'
                GROUP BY uuid, finish, price_date
            ),
            latest_ck_offers AS (
                SELECT c.uuid, c.finish, c.price_date AS ck_date, c.ck_price
                FROM ck_buylist_prices c
                WHERE c.price_date >= (SELECT MAX(price_date) - INTERVAL 3 DAY FROM fact_prices WHERE format = 'paper')
                QUALIFY ROW_NUMBER() OVER(PARTITION BY c.uuid, c.finish ORDER BY c.price_date DESC) = 1
            ),
            asof_aligned AS (
                SELECT
                    c.uuid, c.finish, c.ck_date AS price_date, t.price_date AS tcg_date,
                    t.tcg_price, c.ck_price,
                    (t.tcg_price * 1.075 + CASE WHEN t.tcg_price < 5.00 THEN 0.99 ELSE 0.15 END + 0.09) AS total_acquisition_basis,
                    (c.ck_price * 1.30) AS ck_store_credit_payout
                FROM latest_ck_offers c
                ASOF JOIN tcg_prices t
                    ON c.uuid = t.uuid AND c.finish = t.finish AND c.ck_date >= t.price_date
                WHERE t.tcg_price IS NOT NULL AND DATE_DIFF('day', t.price_date, c.ck_date) <= 3
            )
            SELECT
                uuid, price_date, finish, ROUND(tcg_price, 2) AS tcg_price, ROUND(ck_price, 2) AS ck_price,
                ROUND(ck_store_credit_payout - total_acquisition_basis, 2) AS price_spread,
                ROUND(((ck_store_credit_payout - total_acquisition_basis) / NULLIF(total_acquisition_basis, 0)) * 100.0, 2) AS spread_pct
            FROM asof_aligned
            WHERE ck_store_credit_payout > total_acquisition_basis;
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_features_lookup ON fact_card_features(uuid, finish);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_training_date ON fact_training_dataset(price_date);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_arb_spread ON fact_arbitrage_opportunities(price_spread DESC);")
        conn.execute("CHECKPOINT;")
        conn.execute("VACUUM;")
    finally:
        conn.close()

if __name__ == "__main__":
    build_analytical_features(str(DB_PATH))