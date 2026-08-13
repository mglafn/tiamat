import os
import duckdb
import pandas as pd
from extract_prices import stream_mtg_prices

def parse_and_batch_records(raw_json_path, batch_size=50000):
    """
    Flattens deeply nested MTGJSON dictionaries and yields batches of flat dicts.
    """
    records_batch = []
    for uuid, price_data in stream_mtg_prices(raw_json_path):
        for card_format, vendors in price_data.items():
            if not isinstance(vendors, dict):
                continue
            for vendor, vendor_data in vendors.items():
                if not isinstance(vendor_data, dict) or 'retail' not in vendor_data:
                    continue
                retail_data = vendor_data['retail']
                for finish, date_prices in retail_data.items():
                    if not isinstance(date_prices, dict):
                        continue
                    for date_str, price in date_prices.items():
                        records_batch.append({
                            'uuid': uuid,
                            'format': card_format,
                            'vendor': vendor,
                            'finish': finish,
                            'price_date': date_str,
                            'price': float(price)
                        })
                        if len(records_batch) >= batch_size:
                            yield pd.DataFrame(records_batch)
                            records_batch = []
    if records_batch:
        yield pd.DataFrame(records_batch)

def load_dimension_cards(conn, cards_csv_path):
    """
    Infers schema and ingests dim_cards catalog from cards.csv directly into DuckDB.
    Creates a Master Data Management (MDM) dimension table.
    """
    print(f"Ingesting dimension catalog from {cards_csv_path}...")
    conn.execute("DROP TABLE IF EXISTS dim_cards")
    conn.execute(f"""
        CREATE TABLE dim_cards AS 
        SELECT 
            uuid, 
            name, 
            setCode as set_code, 
            rarity
        FROM read_csv_auto('{cards_csv_path}', ignore_errors=true)
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_name ON dim_cards(name);")
    count = conn.execute("SELECT COUNT(*) FROM dim_cards").fetchone()[0]
    print(f"Dimension table 'dim_cards' loaded with {count:,} cards.\n")

def main():
    raw_data_path = os.path.join("data", "raw", "AllPrices.json")
    cards_csv_path = os.path.join("data", "raw", "cards.csv")
    db_path = os.path.join("data", "mtg_prices.duckdb")

    conn = duckdb.connect(db_path)

    # 1. Ingest Fact Table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fact_prices (
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
    for df_batch in parse_and_batch_records(raw_data_path):
        conn.execute("INSERT INTO fact_prices SELECT * FROM df_batch")
        total_rows += len(df_batch)
        print(f"Ingested batch... Total rows so far: {total_rows:,}")
    print(f"Fact table complete! Total records loaded: {total_rows:,}\n")

    # 2. Ingest Dimension Table (Star Schema)
    if os.path.exists(cards_csv_path):
        load_dimension_cards(conn, cards_csv_path)
    else:
        print(f"Warning: {cards_csv_path} not found. Skipping dim_cards creation.")

    conn.close()

if __name__ == "__main__":
    main()