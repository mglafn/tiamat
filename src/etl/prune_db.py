import os
import sys
from pathlib import Path
import duckdb

BASE_DIR = Path(__file__).resolve().parent
FULL_DB = BASE_DIR / "data" / "mtg_prices_full.duckdb"
PROD_DB = BASE_DIR / "data" / "mtg_prices.duckdb"


def create_production_snapshot(lookback_days: int = 60):
    if PROD_DB.exists() and not FULL_DB.exists():
        print(f"Renaming {PROD_DB.name} -> {FULL_DB.name}")
        os.rename(PROD_DB, FULL_DB)

    if not FULL_DB.exists():
        print(f"Source database not found at {FULL_DB}", file=sys.stderr)
        sys.exit(1)

    if PROD_DB.exists():
        os.remove(PROD_DB)

    src_conn = duckdb.connect(str(FULL_DB), read_only=True)
    dst_conn = duckdb.connect(str(PROD_DB))

    try:
        dst_conn.execute("CREATE TABLE dim_cards AS SELECT * FROM src_conn.dim_cards")
        dst_conn.execute("CREATE TABLE fact_arbitrage_opportunities AS SELECT * FROM src_conn.fact_arbitrage_opportunities")

        dst_conn.execute(f"""
            CREATE TABLE fact_card_features AS 
            SELECT * FROM src_conn.fact_card_features 
            WHERE price_date >= (
                SELECT MAX(price_date) - INTERVAL {lookback_days} DAY 
                FROM src_conn.fact_card_features
            )
        """)

        dst_conn.execute(f"""
            CREATE TABLE fact_prices AS 
            SELECT * FROM src_conn.fact_prices 
            WHERE format = 'paper' 
              AND price_date >= (
                  SELECT MAX(price_date) - INTERVAL {lookback_days} DAY 
                  FROM src_conn.fact_prices
              )
        """)

        dst_conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_name ON dim_cards(name);")
        dst_conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_uuid ON dim_cards(uuid);")
        dst_conn.execute("CREATE INDEX IF NOT EXISTS idx_fact_prices_lookup ON fact_prices(uuid, vendor, finish, list_type, format);")
        dst_conn.execute("CREATE INDEX IF NOT EXISTS idx_fact_prices_date ON fact_prices(price_date);")
        dst_conn.execute("CREATE INDEX IF NOT EXISTS idx_features_uuid_finish_date ON fact_card_features(uuid, finish, price_date);")
        dst_conn.execute("CREATE INDEX IF NOT EXISTS idx_arb_spread ON fact_arbitrage_opportunities(price_spread DESC);")

        dst_conn.execute("CHECKPOINT;")

        size_mb = PROD_DB.stat().st_size / (1024 * 1024)
        print(f"Snapshot created: {PROD_DB} ({size_mb:.2f} MB)")

    finally:
        src_conn.close()
        dst_conn.close()


if __name__ == "__main__":
    create_production_snapshot()