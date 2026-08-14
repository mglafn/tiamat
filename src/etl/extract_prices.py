import ijson
import os
from pathlib import Path


def stream_mtg_prices(file_path):
    """
    Generator function to lazily stream the MTGJSON pricing payload.
    Yields one card's pricing history at a time to keep RAM usage under 150MB.
    """
    path_str = str(file_path)
    print(f"Starting stream extraction from {path_str}...")
    with open(path_str, 'rb') as f:
        card_stream = ijson.kvitems(f, 'data')
        for card_uuid, price_data in card_stream:
            yield card_uuid, price_data


def main():
    raw_data_path = os.path.join("data", "raw", "AllPrices.json")
    if not os.path.exists(raw_data_path):
        print("Please download AllPrices.json from MTGJSON and place it in data/raw/")
        return
    processed_count = 0
    for uuid, data in stream_mtg_prices(raw_data_path):
        print(f"Found UUID: {uuid}")
        print(f"Data keys available: {list(data.keys())}\n")
        processed_count += 1
        if processed_count >= 3:
            print("Successfully streamed 3 records. Exiting test run.")
            break


if __name__ == "__main__":
    main()