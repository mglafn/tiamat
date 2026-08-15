import os
from pathlib import Path
import duckdb


def build_analytical_features(db_path: str):
    print(f"Connecting to DuckDB at {db_path} to build analytical features...")
    conn = duckdb.connect(db_path)

    try:
        # --------------------------------------------------------------------------
        # 1. Base Feature Table (Calendar-Based SMAs, Volatility, Physical Paper Only)
        # --------------------------------------------------------------------------
        print("Building 'fact_card_features'...")
        conn.execute("DROP TABLE IF EXISTS fact_card_features")
        conn.execute("""
            CREATE TABLE fact_card_features AS
            WITH base_paper_retail AS (
                SELECT 
                    f.uuid,
                    f.vendor,
                    f.finish,
                    f.price_date,
                    f.price AS current_price,
                    -- Calendar-day moving averages (handles sparse/missing trading days)
                    AVG(f.price) OVER (
                        PARTITION BY f.uuid, f.vendor, f.finish 
                        ORDER BY f.price_date ASC
                        RANGE BETWEEN INTERVAL 6 DAYS PRECEDING AND CURRENT ROW
                    ) AS sma_7,
                    AVG(f.price) OVER (
                        PARTITION BY f.uuid, f.vendor, f.finish 
                        ORDER BY f.price_date ASC
                        RANGE BETWEEN INTERVAL 29 DAYS PRECEDING AND CURRENT ROW
                    ) AS sma_30,
                    -- Normalized daily return: scaled by days elapsed to prevent multi-day gap volatility spikes
                    ((f.price - LAG(f.price) OVER (
                        PARTITION BY f.uuid, f.vendor, f.finish 
                        ORDER BY f.price_date ASC
                    )) / NULLIF(LAG(f.price) OVER (
                        PARTITION BY f.uuid, f.vendor, f.finish 
                        ORDER BY f.price_date ASC
                    ), 0) * 100.0) / GREATEST(1, DATE_DIFF('day', LAG(f.price_date) OVER (
                        PARTITION BY f.uuid, f.vendor, f.finish 
                        ORDER BY f.price_date ASC
                    ), f.price_date)) AS daily_return_pct
                FROM fact_prices f
                WHERE f.list_type = 'retail' 
                  AND f.format = 'paper'
            )
            SELECT 
                b.uuid,
                b.vendor,
                b.finish,
                b.price_date,
                b.current_price,
                b.sma_7,
                b.sma_30,
                b.daily_return_pct,
                -- 7-Day Velocity: relative spread to the 7-day moving average
                ((b.current_price - b.sma_7) / NULLIF(b.sma_7, 0)) * 100.0 AS velocity_7d_pct,
                -- Short-term vs long-term moving average ratio
                (b.sma_7 / NULLIF(b.sma_30, 0)) AS sma_ratio,
                -- 14-day rolling volatility
                STDDEV(b.daily_return_pct) OVER (
                    PARTITION BY b.uuid, b.vendor, b.finish 
                    ORDER BY b.price_date ASC
                    RANGE BETWEEN INTERVAL 13 DAYS PRECEDING AND CURRENT ROW
                ) AS volatility_14d,
                CASE WHEN b.finish = 'foil' THEN 1 ELSE 0 END AS is_foil,
                CASE 
                    WHEN d.rarity = 'mythic' THEN 4 
                    WHEN d.rarity = 'rare' THEN 3 
                    WHEN d.rarity = 'uncommon' THEN 2 
                    ELSE 1 
                END AS rarity_score,
                d.edhrec_rank
            FROM base_paper_retail b
            LEFT JOIN dim_cards d ON b.uuid = d.uuid;
        """)

        # --------------------------------------------------------------------------
        # 2. ML Training Dataset (Temporal ASOF Alignment for 7D Forward Target)
        # --------------------------------------------------------------------------
        print("Building 'fact_training_dataset' using ASOF temporal joins...")
        conn.execute("DROP TABLE IF EXISTS fact_training_dataset")
        conn.execute("""
            CREATE TABLE fact_training_dataset AS
                SELECT 
                    uuid, vendor, finish, price_date,
                    current_price, sma_ratio, volatility_14d, daily_return_pct, 
                    velocity_7d_pct, is_foil, rarity_score, edhrec_rank,
                    
                    -- Replaces ASOF JOIN: Safely grabs the first price between 7 and 10 days in the future
                    ((first_value(current_price IGNORE NULLS) OVER (
                        PARTITION BY uuid, vendor, finish 
                        ORDER BY price_date ASC
                        RANGE BETWEEN INTERVAL 7 DAYS FOLLOWING AND INTERVAL 10 DAYS FOLLOWING
                    ) - current_price) / NULLIF(current_price, 0)) * 100.0 AS target_return_7d_pct
                    
                FROM fact_card_features;
                """)

        # --------------------------------------------------------------------------
        # 3. Arbitrage Opportunities (Per-Vendor Fresh Quotes & Inbound Friction)
        # --------------------------------------------------------------------------
        print("Building 'fact_arbitrage_opportunities'...")
        conn.execute("DROP TABLE IF EXISTS fact_arbitrage_opportunities")
        conn.execute("""
            CREATE TABLE fact_arbitrage_opportunities AS
            WITH max_db_date AS (
                SELECT MAX(price_date) AS max_date FROM fact_prices WHERE format = 'paper'
            ),
            latest_prices AS (
                SELECT f.uuid, f.vendor, f.list_type, f.finish, f.price_date, f.price
                FROM fact_prices f, max_db_date m
                WHERE f.format = 'paper'
                  AND f.price_date >= (m.max_date - INTERVAL 3 DAY)
                QUALIFY ROW_NUMBER() OVER(
                    PARTITION BY f.uuid, f.vendor, f.list_type, f.finish 
                    ORDER BY f.price_date DESC
                ) = 1
            ),
            tcg_retail AS (
                SELECT uuid, finish, price_date, MIN(price) AS tcg_price
                FROM latest_prices 
                WHERE vendor = 'tcgplayer' AND list_type = 'retail'
                GROUP BY uuid, finish, price_date
            ),
            ck_buylist AS (
                SELECT uuid, finish, price_date, MAX(price) AS ck_price
                FROM latest_prices 
                WHERE vendor = 'cardkingdom' AND list_type = 'buylist'
                GROUP BY uuid, finish, price_date
            )
            SELECT 
                t.uuid,
                t.price_date,
                t.finish,
                t.tcg_price,
                c.ck_price,
                -- Buying on TCG: Item + 7.5% sales tax + $0.99 inbound shipping if sub-$5. Shipping to CK: $0.10 bulk.
                (c.ck_price - (t.tcg_price * 1.075 + 0.10 + CASE WHEN t.tcg_price < 5.00 THEN 0.99 ELSE 0.0 END)) AS price_spread,
                ((c.ck_price - (t.tcg_price * 1.075 + 0.10 + CASE WHEN t.tcg_price < 5.00 THEN 0.99 ELSE 0.0 END)) / 
                  NULLIF(t.tcg_price * 1.075 + 0.10 + CASE WHEN t.tcg_price < 5.00 THEN 0.99 ELSE 0.0 END, 0)) * 100.0 AS spread_pct
            FROM tcg_retail t
            JOIN ck_buylist c ON t.uuid = c.uuid AND t.finish = c.finish
            WHERE c.ck_price > (t.tcg_price * 1.075 + 0.10 + CASE WHEN t.tcg_price < 5.00 THEN 0.99 ELSE 0.0 END);
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_features_uuid_vendor_date ON fact_card_features(uuid, vendor, price_date);")
        print("Feature engineering successfully completed!")

    finally:
        conn.close()


if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parent.parent.parent
    DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"
    
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}. Run ETL ingestion first.")
    else:
        build_analytical_features(str(DB_PATH))