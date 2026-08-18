"""
src/etl/load_duckdb.py
----------------------
High-performance streaming ETL pipeline for MTGJSON v5 datasets into DuckDB.
Safely extracts retail and buylist price points across finishes (normal, foil, etched)
and ingests card fundamentals into dimensional store dim_cards.
"""

import os
import sys
from pathlib import Path
from typing import Generator, Dict, Any
import duckdb
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "src" / "etl"))

try:
    from extract_prices import stream_mtg_prices
except ImportError:
    from src.etl.extract_prices import stream_mtg_prices


def parse_and_batch_records(raw_json_path: Path, batch_size: int = 50000) -> Generator[pd.DataFrame, None, None]:
    """
    Lazily parses deeply nested MTGJSON price dictionaries with defensive type guards.
    Extracts paper/mtgo format, vendors, list types (retail/buylist), finishes (normal/foil/etched),
    and calendar price observations without exceeding memory budgets.
    """
    records_batch = []
    
    for uuid, price_data in stream_mtg_prices(str(raw_json_path)):
        if not isinstance(price_data, dict):
            continue
        
        for card_format, vendors in price_data.items():
            if not isinstance(vendors, dict):
                continue
            
            for vendor, vendor_data in vendors.items():
                if not isinstance(vendor_data, dict):
                    continue

                for list_type in ("retail", "buylist"):
                    list_data = vendor_data.get(list_type)
                    if not isinstance(list_data, dict):
                        continue
                    
                    for finish in ("normal", "foil", "etched"):
                        date_prices = list_data.get(finish)
                        if not isinstance(date_prices, dict):
                            continue
                        
                        for date_str, price in date_prices.items():
                            try:
                                price_float = float(price)
                            except (ValueError, TypeError):
                                continue

                            # Enforce positive price sanity
                            if price_float <= 0.0:
                                continue

                            records_batch.append({
                                "uuid": str(uuid),
                                "format": str(card_format),
                                "vendor": str(vendor),
                                "list_type": str(list_type),
                                "finish": str(finish),
                                "price_date": str(date_str),
                                "price": price_float
                            })

                            if len(records_batch) >= batch_size:
                                yield pd.DataFrame(records_batch)
                                records_batch = []

    if records_batch:
        yield pd.DataFrame(records_batch)


def load_dimension_cards(conn: duckdb.DuckDBPyConnection, cards_csv_path: Path):
    """
    Ingests and enriches the dim_cards dimensional table directly from cards.csv into DuckDB.
    Normalizes types (Creature, Land, Battle, Planeswalker), Reserved List status, and release dates.
    """
    posix_path = cards_csv_path.as_posix()
    print(f"Ingesting enriched dimension catalog from {posix_path}...")
    conn.execute("DROP TABLE IF EXISTS dim_cards")
    conn.execute(f"""
        CREATE TABLE dim_cards AS 
        SELECT 
            uuid, 
            name, 
            COALESCE(setCode, 'OTC') AS set_code, 
            number AS collector_number, 
            rarity,
            TRY_CAST(edhrecRank AS INTEGER) AS edhrec_rank,
            COALESCE(TRY_CAST(isOnlineOnly AS BOOLEAN), false) AS is_online_only,
            COALESCE(TRY_CAST(isReserved AS BOOLEAN), false) AS is_reserved,
            COALESCE(TRY_CAST(manaValue AS DOUBLE), 0.0) AS mana_value,
            COALESCE(types, 'Unknown') AS card_type,
            TRY_CAST(originalReleaseDate AS DATE) AS original_release_date
        FROM read_csv_auto('{posix_path}', header=true, ignore_errors=true)
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_name ON dim_cards(name);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_uuid ON dim_cards(uuid);")
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

    try:
        conn.execute("DROP TABLE IF EXISTS fact_prices")
        conn.execute("""
            CREATE TABLE fact_prices (
                uuid VARCHAR,
                format VARCHAR,
                vendor VARCHAR,
                list_type VARCHAR,
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
                    list_type, 
                    finish, 
                    CAST(price_date AS DATE), 
                    price 
                FROM df_batch_view
            """)
            conn.unregister("df_batch_view")
            total_rows += len(df_batch)
            print(f"  -> Ingested batch... Total records loaded: {total_rows:,}")

        print(f"Fact table complete! Total records loaded: {total_rows:,}\n")

        print("Building analytical indexes on fact_prices...")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fact_prices_lookup ON fact_prices(uuid, vendor, finish, list_type, format);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fact_prices_date ON fact_prices(price_date);")

        if cards_csv_path.exists():
            load_dimension_cards(conn, cards_csv_path)
        else:
            print(f"Warning: {cards_csv_path} not found. Skipping dim_cards creation.")

    finally:
        conn.close()
        print("DuckDB connection closed successfully.")


if __name__ == "__main__":
    main()