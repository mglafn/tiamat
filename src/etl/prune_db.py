import os
import sys
from pathlib import Path
import duckdb

BASE_DIR = Path(__file__).resolve().parent.parent.parent
FULL_DB = BASE_DIR / "data" / "mtg_prices_full.duckdb"
PROD_DB = BASE_DIR / "data" / "mtg_prices.duckdb"


def create_production_snapshot():
    src_db = FULL_DB if FULL_DB.exists() else PROD_DB
    if not src_db.exists():
        print(f"Source database not found at {src_db}", file=sys.stderr)
        sys.exit(1)

    temp_prod = BASE_DIR / "data" / "mtg_prices_pruned.duckdb"
    if temp_prod.exists():
        os.remove(temp_prod)

    conn = duckdb.connect(str(temp_prod), config={
        'max_memory': '1.5GB',
        'threads': '2',
        'preserve_insertion_order': 'false'
    })
    try:
        conn.execute(f"ATTACH '{src_db.as_posix()}' AS src (READ_ONLY);")

        # Copy enum types if present in source
        conn.execute("""
            CREATE TYPE price_format AS ENUM ('paper', 'mtgo');
            CREATE TYPE price_vendor AS ENUM ('tcgplayer', 'cardkingdom', 'cardmarket', 'cardsphere', 'starcitygames', 'cardhoarder', 'manapool');
            CREATE TYPE price_list_type AS ENUM ('retail', 'buylist');
            CREATE TYPE price_finish AS ENUM ('normal', 'foil', 'etched');
        """)

        # 1. Keep ALL active arbitrage opportunities
        conn.execute("""
            CREATE TABLE fact_arbitrage_opportunities AS
            SELECT * FROM src.fact_arbitrage_opportunities;
        """)

        # 2. Target universe: Top 1,000 EDHREC staples + Reserved List + All Arb Cards
        conn.execute("""
            CREATE TEMP TABLE target_tracked_cards AS
            SELECT DISTINCT uuid FROM src.fact_arbitrage_opportunities
            UNION
            SELECT uuid FROM src.dim_cards
            WHERE (edhrec_rank IS NOT NULL AND edhrec_rank <= 1000)
               OR is_reserved = true;
        """)

        # 3. Features: Last 21 days of history for tracked cards ONLY
        conn.execute("""
            CREATE TABLE fact_card_features AS
            SELECT f.* FROM src.fact_card_features f
            JOIN target_tracked_cards t ON f.uuid = t.uuid
            WHERE f.price_date >= (SELECT MAX(price_date) - INTERVAL 21 DAY FROM src.fact_card_features);
        """)

        # 4. Enriched Dimension Table (tracked cards only)
        conn.execute("""
            CREATE TABLE dim_cards AS
            SELECT
                d.uuid, d.name, d.set_code, d.collector_number, d.rarity,
                d.edhrec_rank, d.is_online_only, d.is_reserved, d.mana_value,
                d.card_type, d.original_release_date
            FROM src.dim_cards d
            WHERE d.is_online_only = false
              AND d.uuid IN (SELECT DISTINCT uuid FROM target_tracked_cards);
        """)

        # 5. Latest Retail Price points for the summary cards
        conn.execute("""
            CREATE TABLE fact_prices AS
            WITH ranked_prices AS (
                SELECT
                    uuid, format, vendor, list_type, finish, price_date, price,
                    ROW_NUMBER() OVER (
                        PARTITION BY uuid, finish, vendor
                        ORDER BY price_date DESC
                    ) AS rn
                FROM src.fact_prices
                WHERE format = 'paper'
                  AND list_type = 'retail'
                  AND vendor IN ('tcgplayer', 'cardkingdom', 'starcitygames')
                  AND uuid IN (SELECT uuid FROM dim_cards)
            )
            SELECT uuid, format, vendor, list_type, finish, price_date, price
            FROM ranked_prices
            WHERE rn = 1;
        """)

        # 6. Essential analytical indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_name ON dim_cards(name);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_uuid ON dim_cards(uuid);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fact_prices_lookup ON fact_prices(uuid, finish);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_features_lookup ON fact_card_features(uuid, finish);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_arb_spread ON fact_arbitrage_opportunities(price_spread DESC);")

        conn.execute("CHECKPOINT;")
        conn.execute("VACUUM;")
        conn.execute("DETACH src;")
        conn.close()

        # Overwrite destination file
        if PROD_DB.exists():
            os.remove(PROD_DB)
        os.rename(temp_prod, PROD_DB)
        size_mb = PROD_DB.stat().st_size / (1024 * 1024)
        print(f"Production snapshot ready: {PROD_DB} ({size_mb:.2f} MB)")
    except Exception as e:
        if temp_prod.exists():
            os.remove(temp_prod)
        raise e


if __name__ == "__main__":
    create_production_snapshot()