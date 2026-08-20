import os
import requests
import lzma
import shutil

URLS = {
    "AllPrices.json.xz": "https://mtgjson.com/api/v5/AllPrices.json.xz",
    "cards.csv.xz": "https://mtgjson.com/api/v5/csv/cards.csv.xz"
}

raw_dir = os.path.join("data", "raw")
os.makedirs(raw_dir, exist_ok=True)

for filename, url in URLS.items():
    compressed_path = os.path.join(raw_dir, filename)
    print(f"Downloading {filename}...")
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(compressed_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)

    if filename == "cards.csv.xz":
        extracted_path = os.path.join(raw_dir, "cards.csv")
        print(f"Decompressing {filename}...")
        with lzma.open(compressed_path, "rb") as f_in:
            with open(extracted_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out, length=1024 * 1024)
        os.remove(compressed_path)
        print(f"Ready: {extracted_path}\n")
    else:
        print(f"Ready (retained compressed): {compressed_path}\n")