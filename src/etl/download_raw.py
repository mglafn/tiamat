import os
import requests
import lzma
import shutil

url = "https://mtgjson.com/api/v5/AllPrices.json.xz"
raw_dir = os.path.join("data", "raw")
compressed_path = os.path.join(raw_dir, "AllPrices.json.xz")
extracted_path = os.path.join(raw_dir, "AllPrices.json")

os.makedirs(raw_dir, exist_ok=True)

print("Downloading AllPrices.json.xz from MTGJSON...")
response = requests.get(url, stream=True)
with open(compressed_path, "wb") as f:
    for chunk in response.iter_content(chunk_size=1024*1024):
        if chunk:
            f.write(chunk)

print("Decompressing .xz file in memory-efficient chunks...")
with lzma.open(compressed_path, "rb") as f_in:
    with open(extracted_path, "wb") as f_out:
        # Streams the decompression chunk by chunk to prevent RAM spikes
        shutil.copyfileobj(f_in, f_out, length=1024*1024)

os.remove(compressed_path)
print(f"Success! Uncompressed file ready at: {extracted_path}")