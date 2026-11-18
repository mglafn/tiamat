from contextlib import ExitStack
import lzma
from pathlib import Path
import ijson

from src.config import ALL_PRICES_JSON_PATH, ALL_PRICES_XZ_PATH


def stream_mtg_prices(file_path):
    path = Path(file_path)
    print(f"Starting stream extraction from {path}...")
    opener = lzma.open if str(path).endswith(".xz") else open
    with ExitStack() as stack:
        f = stack.enter_context(opener(path, "rb"))
        for card_uuid, price_data in ijson.kvitems(f, "data"):
            yield card_uuid, price_data


def main():
    raw_data_path = ALL_PRICES_XZ_PATH if ALL_PRICES_XZ_PATH.exists() else ALL_PRICES_JSON_PATH
    if not raw_data_path.exists():
        print("Please download AllPrices.json.xz and place it in data/raw/")
        return

    for processed_count, (uuid, data) in enumerate(stream_mtg_prices(raw_data_path), start=1):
        print(f"Found UUID: {uuid}")
        print(f"Data keys available: {list(data.keys())}\n")
        if processed_count >= 3:
            print("Successfully streamed 3 records. Exiting test run.")
            break


if __name__ == "__main__":
    main()
