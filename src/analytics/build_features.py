import os
from pathlib import Path
import duckdb

def compute_financial_indicators(db_path: str):
    base_dir = Path(__file__).resolve().parent.parent.parent
    tmp_dir = base_dir / "data" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    conn = duckdb.connect(db_path)
    print("Configuring DuckDB memory limits and scratch space...")
    
    conn.execute("PRAGMA threads = 4;")
    conn.execute(f"PRAGMA temp_directory = '{tmp_dir.as_posix()}';")
    conn.execute("SET memory_limit = '4GB';")
    
    print("Building quantitative feature store in DuckDB...")
    
    # --------------------------------------------------------------------------
    # 1. FEATURE STORE (Momentum, Volatility & Categorical Encodings)
    # --------------------------------------------------------------------------
    conn.execute("""
        CREATE OR REPLACE TABLE fact_card_features AS
        WITH filtered_prices AS (
            SELECT 
                p.uuid, p.vendor, p.finish, p.price_date, p.price,
                COALESCE(d.edhrec_rank, 50000) AS edhrec_rank,
                CASE 
                    WHEN LOWER(d.rarity) = 'mythic' THEN 4
                    WHEN LOWER(d.rarity) = 'rare' THEN 3
                    WHEN LOWER(d.rarity) = 'uncommon' THEN 2
                    WHEN LOWER(d.rarity) = 'common' THEN 1
                    ELSE 0 
                END AS rarity_score,
                CASE WHEN LOWER(p.finish) = 'foil' THEN 1 ELSE 0 END AS is_foil
            FROM fact_prices p
            LEFT JOIN dim_cards d ON p.uuid = d.uuid
            WHERE p.format = 'paper' 
              AND p.list_type = 'retail'
              AND p.price > 0
              AND p.price_date >= (
                  SELECT COALESCE(MAX(price_date), CURRENT_DATE) - INTERVAL '365 days' 
                  FROM fact_prices
              )
        ),
        daily_returns AS (
            SELECT *,
                LAG(price, 1) OVER (PARTITION BY uuid, vendor, finish ORDER BY price_date) AS prev_price_1d
            FROM filtered_prices
        ),
        base_features AS (
            SELECT *,
                CASE WHEN prev_price_1d > 0 THEN ((price - prev_price_1d) / prev_price_1d) * 100.0 ELSE 0.0 END AS daily_return_pct
            FROM daily_returns
        ),
        windowed AS (
            SELECT *,
                AVG(price) OVER (
                    PARTITION BY uuid, vendor, finish 
                    ORDER BY price_date 
                    RANGE BETWEEN INTERVAL 6 DAYS PRECEDING AND CURRENT ROW
                ) AS sma_7,
                AVG(price) OVER (
                    PARTITION BY uuid, vendor, finish 
                    ORDER BY price_date 
                    RANGE BETWEEN INTERVAL 29 DAYS PRECEDING AND CURRENT ROW
                ) AS sma_30,
                -- Fixed: 14-Day Rolling Volatility calculated on Returns, not Absolute Price
                COALESCE(
                    STDDEV_SAMP(daily_return_pct) OVER (
                        PARTITION BY uuid, vendor, finish 
                        ORDER BY price_date 
                        RANGE BETWEEN INTERVAL 13 DAYS PRECEDING AND CURRENT ROW
                    ), 
                    0.0
                ) AS volatility_14d,
                -- Fixed: Time-based 7-day velocity approximation
                FIRST_VALUE(price) OVER (
                    PARTITION BY uuid, vendor, finish
                    ORDER BY price_date
                    RANGE BETWEEN INTERVAL 7 DAYS PRECEDING AND CURRENT ROW
                ) AS prev_price_7d_approx
            FROM base_features
        )
        SELECT 
            uuid, vendor, finish, price_date, price AS current_price,
            ROUND(sma_7, 4) AS sma_7,
            ROUND(sma_30, 4) AS sma_30,
            ROUND(CASE WHEN sma_30 > 0 THEN (sma_7 / sma_30) ELSE 1.0 END, 4) AS sma_ratio,
            ROUND(volatility_14d, 4) AS volatility_14d,
            ROUND(daily_return_pct, 4) AS daily_return_pct,
            ROUND(
                CASE 
                    WHEN prev_price_7d_approx > 0 THEN ((price - prev_price_7d_approx) / prev_price_7d_approx) * 100.0
                    ELSE 0.0 
                END, 4
            ) AS velocity_7d_pct,
            is_foil, rarity_score, edhrec_rank
        FROM windowed;
    """)
    
    conn.execute("CREATE INDEX IF NOT EXISTS idx_features_lookup ON fact_card_features(uuid, vendor, finish, price_date);")

    # --------------------------------------------------------------------------
    # 2. ML TRAINING DATASET (True 7-Day Calendar Forward Returns)
    # --------------------------------------------------------------------------
    print("Generating ML training dataset with calendar-aligned 7-day targets...")
    conn.execute("""
        CREATE OR REPLACE TABLE fact_training_dataset AS
        WITH temporal_targets AS (
            SELECT 
                t1.*,
                t2.current_price AS future_price_7d
            FROM fact_card_features t1
            ASOF LEFT JOIN fact_card_features t2 
              ON t1.uuid = t2.uuid 
             AND t1.vendor = t2.vendor 
             AND t1.finish = t2.finish 
             AND t2.price_date >= t1.price_date + INTERVAL '7 days'
             AND t2.price_date <= t1.price_date + INTERVAL '10 days'
        )
        SELECT 
            uuid, vendor, finish, price_date, current_price,
            sma_7, sma_30, sma_ratio, volatility_14d,
            daily_return_pct, velocity_7d_pct,
            is_foil, rarity_score, edhrec_rank,
            future_price_7d,
            ROUND(
                CASE 
                    WHEN current_price > 0 AND future_price_7d IS NOT NULL 
                    THEN ((future_price_7d - current_price) / current_price) * 100.0
                    ELSE NULL 
                END, 4
            ) AS target_return_7d_pct
        FROM temporal_targets;
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_training_dataset_uuid ON fact_training_dataset(uuid, vendor, finish, price_date);")

    # --------------------------------------------------------------------------
    # 3. ACTIONABLE CROSS-VENDOR ARBITRAGE
    # --------------------------------------------------------------------------
    print("Materializing net cross-vendor arbitrage opportunities...")
    conn.execute("""
        CREATE OR REPLACE TABLE fact_arbitrage_opportunities AS
        WITH ranked_prices AS (
            SELECT 
                uuid, price_date, finish, vendor, list_type, price,
                ROW_NUMBER() OVER(PARTITION BY uuid, vendor, finish, list_type ORDER BY price_date DESC) as rn
            FROM fact_prices
            WHERE format = 'paper'
        ),
        pivoted AS (
            SELECT 
                uuid, finish,
                MAX(price_date) AS latest_overlap_date,
                MIN(CASE WHEN vendor = 'tcgplayer' AND list_type = 'retail' THEN price END) AS tcg_retail,
                MIN(CASE WHEN vendor = 'cardkingdom' AND list_type = 'buylist' THEN price END) AS ck_buylist
            FROM ranked_prices
            WHERE rn = 1
            GROUP BY uuid, finish
        )
        SELECT 
            uuid, latest_overlap_date AS price_date, finish,
            tcg_retail AS tcg_price,
            ck_buylist AS ck_price,
            ROUND(ck_buylist - (tcg_retail * 1.10 + 1.00), 2) AS price_spread,
            ROUND(
                CASE 
                    WHEN tcg_retail > 0 
                    THEN ((ck_buylist - (tcg_retail * 1.10 + 1.00)) / (tcg_retail * 1.10 + 1.00)) * 100.0
                    ELSE 0.0 
                END, 2
            ) AS spread_pct
        FROM pivoted
        WHERE tcg_retail IS NOT NULL 
          AND ck_buylist IS NOT NULL
          AND (ck_buylist - (tcg_retail * 1.10 + 1.00)) > 0.00;
    """)
    conn.close()
    print("Quantitative features, ML targets, and arbitrage datasets built successfully!")


if __name__ == "__main__":
    DB_PATH = os.path.join("data", "mtg_prices.duckdb")
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file not found at {DB_PATH}. Run ETL first.")
    else:
        compute_financial_indicators(DB_PATH)