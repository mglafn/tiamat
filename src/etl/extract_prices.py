import ijson
import lzma
import os
from pathlib import Path


def stream_mtg_prices(file_path):
    path = Path(file_path)
    path_str = str(path)
    print(f"Starting stream extraction from {path_str}...")

    if path_str.endswith(".xz"):
        with lzma.open(path, "rb") as f:
            card_stream = ijson.kvitems(f, "data")
            for card_uuid, price_data in card_stream:
                yield card_uuid, price_data
    else:
        with open(path, "rb") as f:
            card_stream = ijson.kvitems(f, "data")
            for card_uuid, price_data in card_stream:
                yield card_uuid, price_data


def main():
    raw_data_path = Path("data") / "raw" / "AllPrices.json.xz"
    if not raw_data_path.exists():
        raw_data_path = Path("data") / "raw" / "AllPrices.json"

    if not raw_data_path.exists():
        print("Please download AllPrices.json.xz and place it in data/raw/")
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