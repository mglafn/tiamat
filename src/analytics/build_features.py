import os
import duckdb

def compute_financial_indicators(db_path):
    conn = duckdb.connect(db_path)
    print("Computing rolling financial indicators & arbitrage spreads in DuckDB...")

    # 1. Create Indexes on raw table for high-speed windowing
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prices ON fact_prices (uuid, vendor, price_date);")

    # 2. Compute 7-day, 30-day SMA and Daily Returns using SQL Window Functions
    conn.execute("""
        CREATE OR REPLACE TABLE fact_card_features AS
        WITH daily_prices AS (
            SELECT 
                uuid,
                vendor,
                finish,
                price_date,
                price,
                -- Lagged price for daily return calculation
                LAG(price, 1) OVER (PARTITION BY uuid, vendor, finish ORDER BY price_date) as prev_price,
                -- 7-Day Simple Moving Average
-- 7-Day Simple Moving Average (Interval Aware)
                AVG(price) OVER (
                    PARTITION BY uuid, vendor, finish 
                    ORDER BY price_date 
                    RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
                ) as sma_7,
                -- 30-Day Simple Moving Average (Interval Aware)
                AVG(price) OVER (
                    PARTITION BY uuid, vendor, finish 
                    ORDER BY price_date 
                    RANGE BETWEEN INTERVAL '29 days' PRECEDING AND CURRENT ROW
                ) as sma_30
            FROM fact_prices
            WHERE format = 'paper' -- Focus on physical paper cards first
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
        FROM daily_prices;
    """)

    # 2.5 Build ML Training Dataset with 7-Day Lead Target
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
            -- Look forward 7 days within the same card/vendor/finish group
            LEAD(price, 7) OVER (
                PARTITION BY uuid, vendor, finish 
                ORDER BY price_date
            ) AS target_price_7d
        FROM fact_card_features;
    """)

    # 3. Create an Arbitrage Table: Compare prices across vendors on the exact same date
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
          AND (ck_price - tcg_price) > 2.00; -- Flag gaps where spread is > $2.00
    """)

    print("Feature Engineering Complete! View tables created:")
    print(" - fact_card_features (Rolling SMAs & Daily Returns)")
    print(" - fact_arbitrage_opportunities (Cross-Vendor Price Spreads)")
    
    conn.close()

if __name__ == "__main__":
    db_path = os.path.join("data", "mtg_prices.duckdb")
    compute_financial_indicators(db_path)