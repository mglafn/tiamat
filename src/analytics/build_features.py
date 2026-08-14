import os
from pathlib import Path
import duckdb

def compute_financial_indicators(db_path):
    # 1. Setup absolute path for disk-spilling
    base_dir = Path(__file__).resolve().parent.parent.parent
    tmp_dir = base_dir / "data" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    conn = duckdb.connect(db_path)
    print("Configuring DuckDB memory limits and disk-spilling...")
    
    # Restrict threads and assign temp directory to prevent laptop OOM
    conn.execute("PRAGMA threads = 2;")
    conn.execute(f"PRAGMA temp_directory = '{tmp_dir.as_posix()}';")
    conn.execute("SET memory_limit = '3GB';")
    
    print("Computing rolling financial indicators & arbitrage spreads in DuckDB...")
    
    # 2. Compute 7-day, 30-day SMA and Daily Returns using Optimized Row Windows
    conn.execute("""
        CREATE OR REPLACE TABLE fact_card_features AS
        WITH recent_prices AS (
            SELECT 
                uuid,
                vendor,
                finish,
                price_date,
                price
            FROM fact_prices
            WHERE format = 'paper' 
              -- Filter to last 180 days of market history to keep RAM low
              AND price_date >= (SELECT COALESCE(MAX(price_date), CURRENT_DATE) - INTERVAL '180 days' FROM fact_prices)
        ),
        windowed AS (
            SELECT 
                uuid,
                vendor,
                finish,
                price_date,
                price,
                -- 1-day lag for return calculation
                LAG(price, 1) OVER (PARTITION BY uuid, vendor, finish ORDER BY price_date) as prev_price,
                -- 7-Row Simple Moving Average (Vectorized)
                AVG(price) OVER (
                    PARTITION BY uuid, vendor, finish 
                    ORDER BY price_date 
                    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
                ) as sma_7,
                -- 30-Row Simple Moving Average (Vectorized)
                AVG(price) OVER (
                    PARTITION BY uuid, vendor, finish 
                    ORDER BY price_date 
                    ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
                ) as sma_30
            FROM recent_prices
        )
        SELECT 
            uuid,
            vendor,
            finish,
            price_date,
            price,
            sma_7,
            sma_30,
            CASE 
                WHEN prev_price > 0 THEN ((price - prev_price) / prev_price) * 100
                ELSE 0 
            END as daily_return_pct
        FROM windowed;
    """)
    
    # 3. Build ML Training Dataset with 7-Day Lead Target
    print("Building ML Training Dataset with 7-Day Forward Target...")
    conn.execute("""
        CREATE OR REPLACE TABLE fact_training_dataset AS
        SELECT 
            uuid,
            vendor,
            finish,
            price_date,
            price AS current_price,
            sma_7,
            sma_30,
            daily_return_pct,
            -- Look forward 7 days within the partition
            LEAD(price, 7) OVER (
                PARTITION BY uuid, vendor, finish 
                ORDER BY price_date
            ) AS target_price_7d
        FROM fact_card_features;
    """)
    
    # 4. Cross-Vendor Arbitrage View (Captures today's snapshot with spread > $0.00)
    print("Building Cross-Vendor Arbitrage View...")
    conn.execute("""
        CREATE OR REPLACE TABLE fact_arbitrage_opportunities AS
        WITH vendor_pivoted AS (
            SELECT 
                uuid,
                price_date,
                finish,
                MIN(CASE WHEN vendor = 'tcgplayer' THEN price END) as tcg_price,
                MIN(CASE WHEN vendor = 'cardkingdom' THEN price END) as ck_price
            FROM fact_prices
            WHERE format = 'paper'
              -- Pick the latest available market date
              AND price_date = (SELECT MAX(price_date) FROM fact_prices)
            GROUP BY uuid, price_date, finish
        )
        SELECT 
            uuid,
            price_date,
            finish,
            tcg_price,
            ck_price,
            (ck_price - tcg_price) as price_spread,
            CASE 
                WHEN tcg_price > 0 THEN ((ck_price - tcg_price) / tcg_price) * 100 
                ELSE 0 
            END as spread_pct
        FROM vendor_pivoted
        WHERE tcg_price IS NOT NULL AND ck_price IS NOT NULL
          AND (ck_price - tcg_price) > 0.00;
    """)
    
    print("Feature Engineering Complete! Tables created successfully.")
    conn.close()

if __name__ == "__main__":
    db_path = os.path.join("data", "mtg_prices.duckdb")
    compute_financial_indicators(db_path)