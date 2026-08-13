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
        # Navigate through paper/mtgo formats
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

def main():
    raw_data_path = os.path.join("data", "raw", "AllPrices.json")
    db_path = os.path.join("data", "mtg_prices.duckdb")
    
    # Initialize DuckDB connection
    conn = duckdb.connect(db_path)
    
    # Create target table
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
    
    print("Beginning DuckDB batch ingestion...")
    total_rows = 0
    
    for df_batch in parse_and_batch_records(raw_data_path):
        # High-performance DuckDB insertion directly from Pandas DataFrames
        conn.execute("INSERT INTO fact_prices SELECT * FROM df_batch")
        total_rows += len(df_batch)
        print(f"Ingested batch... Total rows so far: {total_rows:,}")
        
    print(f"Ingestion complete! Total records loaded into DuckDB: {total_rows:,}")
    conn.close()

if __name__ == "__main__":
    main()