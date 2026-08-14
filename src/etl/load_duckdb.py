import os
import sys
from pathlib import Path
import duckdb
import pandas as pd

# ------------------------------------------------------------------------------
# Robust Path & Import Resolution
# ------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "src" / "etl"))

try:
    from extract_prices import stream_mtg_prices
except ImportError:
    from src.etl.extract_prices import stream_mtg_prices


def parse_and_batch_records(raw_json_path: Path, batch_size: int = 50000):
    """
    Flattens deeply nested MTGJSON dictionaries and yields batches of flat dicts.
    """
    records_batch = []
    for uuid, price_data in stream_mtg_prices(str(raw_json_path)):
        if not isinstance(price_data, dict):
            continue
        for card_format, vendors in price_data.items():
            if not isinstance(vendors, dict):
                continue
            for vendor, vendor_data in vendors.items():
                if not isinstance(vendor_data, dict) or 'retail' not in vendor_data:
                    continue
                retail_data = vendor_data['retail']
                if not isinstance(retail_data, dict):
                    continue
                for finish, date_prices in retail_data.items():
                    if not isinstance(date_prices, dict):
                        continue
                    for date_str, price in date_prices.items():
                        try:
                            price_float = float(price)
                        except (ValueError, TypeError):
                            continue

                        records_batch.append({
                            'uuid': str(uuid),
                            'format': str(card_format),
                            'vendor': str(vendor),
                            'finish': str(finish),
                            'price_date': str(date_str),
                            'price': price_float
                        })
                        if len(records_batch) >= batch_size:
                            yield pd.DataFrame(records_batch)
                            records_batch = []
    if records_batch:
        yield pd.DataFrame(records_batch)


def load_dimension_cards(conn: duckdb.DuckDBPyConnection, cards_csv_path: Path):
    """
    Infers schema and ingests dim_cards catalog from cards.csv directly into DuckDB.
    Uses forward slashes (.as_posix()) to prevent Windows backslash escape errors.
    """
    posix_path = cards_csv_path.as_posix()
    print(f"Ingesting dimension catalog from {posix_path}...")
    conn.execute("DROP TABLE IF EXISTS dim_cards")
    conn.execute(f"""
        CREATE TABLE dim_cards AS 
        SELECT 
            uuid, 
            name, 
            COALESCE(setCode, 'OTC') as set_code, 
            rarity
        FROM read_csv_auto('{posix_path}', header=true, ignore_errors=true)
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_name ON dim_cards(name);")
    count = conn.execute("SELECT COUNT(*) FROM dim_cards").fetchone()[0]
    print(f"Dimension table 'dim_cards' loaded with {count:,} cards.\n")


def main():
    raw_dir = BASE_DIR / "data" / "raw"
    db_dir = BASE_DIR / "data"
    raw_dir.mkdir(parents=True, exist_ok=True)
    db_dir.mkdir(parents=True, exist_ok=True)

    raw_json_path = raw_dir / "AllPrices.json"
    cards_csv_path = raw_dir / "cards.csv"
    db_path = db_dir / "mtg_prices.duckdb"

    if not raw_json_path.exists():
        print(f"Error: Raw JSON file not found at {raw_json_path}.")
        print("Please run `python src/etl/download_raw.py` first.")
        sys.exit(1)

    print(f"Connecting to DuckDB at: {db_path}")
    conn = duckdb.connect(str(db_path))

    # 1. Ingest Fact Table
    conn.execute("DROP TABLE IF EXISTS fact_prices")
    conn.execute("""
        CREATE TABLE fact_prices (
            uuid VARCHAR,
            format VARCHAR,
            vendor VARCHAR,
            finish VARCHAR,
            price_date DATE,
            price DOUBLE
        )
    """)
    print("Beginning DuckDB fact table ingestion...")
    total_rows = 0
    for df_batch in parse_and_batch_records(raw_json_path):
        conn.register("df_batch_view", df_batch)
        conn.execute("""
            INSERT INTO fact_prices 
            SELECT 
                uuid, 
                format, 
                vendor, 
                finish, 
                CAST(price_date AS DATE), 
                price 
            FROM df_batch_view
        """)
        conn.unregister("df_batch_view")
        total_rows += len(df_batch)
        print(f"  -> Ingested batch... Total records loaded: {total_rows:,}")

    print(f"Fact table complete! Total records loaded: {total_rows:,}\n")

    # 2. Ingest Dimension Table
    if cards_csv_path.exists():
        load_dimension_cards(conn, cards_csv_path)
    else:
        print(f"Warning: {cards_csv_path} not found. Skipping dim_cards creation.")

    conn.close()
    print("DuckDB ingestion finished successfully.")


if __name__ == "__main__":
    main()