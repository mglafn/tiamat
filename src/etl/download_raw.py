"""
Downloads and decompresses raw MTGJSON price and catalog files.
Streams decompression in 1MB chunks to keep memory usage low.
"""

import os
import requests
import lzma
import shutil

URLS = {
    "AllPrices.json": "https://mtgjson.com/api/v5/AllPrices.json.xz",
    "cards.csv": "https://mtgjson.com/api/v5/csv/cards.csv.xz"
}

raw_dir = os.path.join("data", "raw")
os.makedirs(raw_dir, exist_ok=True)

for filename, url in URLS.items():
    compressed_path = os.path.join(raw_dir, f"{filename}.xz")
    extracted_path = os.path.join(raw_dir, filename)

    print(f"Downloading {filename}.xz...")
    response = requests.get(url, stream=True)
    response.raise_for_status()

    with open(compressed_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)

    print(f"Decompressing {filename}.xz in chunks...")
    with lzma.open(compressed_path, "rb") as f_in:
        with open(extracted_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out, length=1024 * 1024)

    os.remove(compressed_path)
    print(f"Ready: {extracted_path}\n")