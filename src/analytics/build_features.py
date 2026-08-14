import os
from pathlib import Path
import duckdb

def compute_financial_indicators(db_path):
    base_dir = Path(__file__).resolve().parent.parent.parent
    tmp_dir = base_dir / "data" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    conn = duckdb.connect(db_path)
    print("Configuring DuckDB memory limits and disk-spilling...")
    
    conn.execute("PRAGMA threads = 2;")
    conn.execute(f"PRAGMA temp_directory = '{tmp_dir.as_posix()}';")
    conn.execute("SET memory_limit = '3GB';")
    
    print("Building advanced quantitative features in DuckDB...")
    
    # 1. Feature Store with Momentum, Volatility & Demand Signals
    conn.execute("""
        CREATE OR REPLACE TABLE fact_card_features AS
        WITH recent_prices AS (
            SELECT 
                p.uuid,
                p.vendor,
                p.finish,
                p.price_date,
                p.price,
                -- Categorical encoding from dim_cards
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
              AND p.price_date >= (SELECT COALESCE(MAX(price_date), CURRENT_DATE) - INTERVAL '180 days' FROM fact_prices)
        ),
        windowed AS (
            SELECT 
                uuid,
                vendor,
                finish,
                price_date,
                price,
                edhrec_rank,
                rarity_score,
                is_foil,
                -- 1-day & 7-day price lags
                LAG(price, 1) OVER (PARTITION BY uuid, vendor, finish ORDER BY price_date) AS prev_price_1d,
                LAG(price, 7) OVER (PARTITION BY uuid, vendor, finish ORDER BY price_date) AS prev_price_7d,
                -- 7-Row & 30-Row Moving Averages
                AVG(price) OVER (
                    PARTITION BY uuid, vendor, finish 
                    ORDER BY price_date 
                    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
                ) AS sma_7,
                AVG(price) OVER (
                    PARTITION BY uuid, vendor, finish 
                    ORDER BY price_date 
                    ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
                ) AS sma_30,
                -- 14-Row Rolling Standard Deviation (Volatility Metric)
                COALESCE(
                    STDDEV_SAMP(price) OVER (
                        PARTITION BY uuid, vendor, finish 
                        ORDER BY price_date 
                        ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
                    ), 
                    0.0
                ) AS volatility_14d
            FROM recent_prices
        )
        SELECT 
            uuid,
            vendor,
            finish,
            price_date,
            price AS current_price,
            sma_7,
            sma_30,
            -- Momentum Oscillator: SMA Cross Ratio
            CASE WHEN sma_30 > 0 THEN (sma_7 / sma_30) ELSE 1.0 END AS sma_ratio,
            -- Rolling Volatility
            volatility_14d,
            -- Daily Return %
            CASE 
                WHEN prev_price_1d > 0 THEN ((price - prev_price_1d) / prev_price_1d) * 100
                ELSE 0.0 
            END AS daily_return_pct,
            -- 7-Day Velocity %
            CASE 
                WHEN prev_price_7d > 0 THEN ((price - prev_price_7d) / prev_price_7d) * 100
                ELSE 0.0 
            END AS velocity_7d_pct,
            -- Categoricals
            is_foil,
            rarity_score,
            edhrec_rank
        FROM windowed;
    """)
    
    # 2. Build ML Training Dataset with 7-Day Target
    print("Generating ML Training Dataset (Lead Window)...")
    conn.execute("""
        CREATE OR REPLACE TABLE fact_training_dataset AS
        SELECT 
            uuid,
            vendor,
            finish,
            price_date,
            current_price,
            sma_7,
            sma_30,
            sma_ratio,
            volatility_14d,
            daily_return_pct,
            velocity_7d_pct,
            is_foil,
            rarity_score,
            edhrec_rank,
            LEAD(current_price, 7) OVER (
                PARTITION BY uuid, vendor, finish 
                ORDER BY price_date
            ) AS target_price_7d
        FROM fact_card_features;
    """)
    
    # 3. Cross-Vendor Arbitrage View
    print("Materializing Cross-Vendor Arbitrage Opportunities...")
    conn.execute("""
        CREATE OR REPLACE TABLE fact_arbitrage_opportunities AS
        WITH vendor_pivoted AS (
            SELECT 
                uuid,
                price_date,
                finish,
                MIN(CASE WHEN vendor = 'tcgplayer' THEN price END) AS tcg_price,
                MIN(CASE WHEN vendor = 'cardkingdom' THEN price END) AS ck_price
            FROM fact_prices
            WHERE format = 'paper'
              AND price_date = (SELECT MAX(price_date) FROM fact_prices)
            GROUP BY uuid, price_date, finish
        )
        SELECT 
            uuid,
            price_date,
            finish,
            tcg_price,
            ck_price,
            (ck_price - tcg_price) AS price_spread,
            CASE 
                WHEN tcg_price > 0 THEN ((ck_price - tcg_price) / tcg_price) * 100 
                ELSE 0 
            END AS spread_pct
        FROM vendor_pivoted
        WHERE tcg_price IS NOT NULL AND ck_price IS NOT NULL
          AND (ck_price - tcg_price) > 0.00;
    """)
    
    print("Advanced Quantitative Feature Engineering Complete!")
    conn.close()

if __name__ == "__main__":
    db_path = os.path.join("data", "mtg_prices.duckdb")
    compute_financial_indicators(db_path)