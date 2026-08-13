import ijson
import os

def stream_mtg_prices(file_path):
    """
    Generator function to lazily stream the 1.2GB MTGJSON file.
    Yields one card's pricing history at a time to keep RAM usage near 0.
    """
    print(f"Starting extraction from {file_path}...")
    
    with open(file_path, 'rb') as f:
        # MTGJSON AllPrices structure is nested under a main "data" key.
        # ijson.kvitems parses dictionary keys and values incrementally.
        card_stream = ijson.kvitems(f, 'data')
        
        for card_uuid, price_data in card_stream:
            # Yield hands control back to the main loop, saving memory
            yield card_uuid, price_data

def main():
    # Path to your downloaded AllPrices.json (store it in data/raw/)
    raw_data_path = os.path.join("data", "raw", "AllPrices.json")
    
    if not os.path.exists(raw_data_path):
        print("Please download AllPrices.json from MTGJSON and place it in data/raw/")
        return

    # Counter for testing
    processed_count = 0
    
    for uuid, data in stream_mtg_prices(raw_data_path):
        print(f"Found UUID: {uuid}")
        print(f"Data keys available: {list(data.keys())}\n")
        
        processed_count += 1
        if processed_count >= 3:
            print("Successfully streamed 3 records. Exiting early to save time.")
            break

if __name__ == "__main__":
    main()