import os
import sys
from pathlib import Path
import duckdb

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich import box
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False

BASE_DIR = Path(__file__).resolve().parent.parent.parent
FULL_DB = BASE_DIR / "data" / "mtg_prices_full.duckdb"
PROD_DB = BASE_DIR / "data" / "mtg_prices.duckdb"


def create_production_snapshot():
    src_db = FULL_DB if FULL_DB.exists() else PROD_DB
    if not src_db.exists():
        if HAS_RICH:
            console.print(f"[bold red]Error:[/bold red] Source database not found at [yellow]{src_db}[/yellow]")
        else:
            print(f"Source database not found at {src_db}", file=sys.stderr)
        sys.exit(1)

    initial_size_mb = src_db.stat().st_size / (1024 * 1024)

    if HAS_RICH:
        console.print(Panel(
            f"[bold white]DuckDB Snapshot Pruning Engine[/bold white]\n"
            f"[dim]Source: {src_db} ({initial_size_mb:.2f} MB)[/dim]",
            box=box.ROUNDED,
            border_style="cyan"
        ))

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

        # 5. Latest Retail Price points for summary cards
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

        # 6. Analytical indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_name ON dim_cards(name);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_uuid ON dim_cards(uuid);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fact_prices_lookup ON fact_prices(uuid, finish);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_features_lookup ON fact_card_features(uuid, finish);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_arb_spread ON fact_arbitrage_opportunities(price_spread DESC);")

        conn.execute("CHECKPOINT;")
        conn.execute("VACUUM;")
        conn.execute("DETACH src;")
        conn.close()

        if PROD_DB.exists():
            os.remove(PROD_DB)
        os.rename(temp_prod, PROD_DB)
        size_mb = PROD_DB.stat().st_size / (1024 * 1024)

        if HAS_RICH:
            table = Table(box=box.ROUNDED, border_style="green", show_header=True, header_style="bold green")
            table.add_column("Database Stage", style="bold white")
            table.add_column("Size", justify="right", style="cyan")
            table.add_column("Compression Delta", justify="right", style="bold green")
            reduction_pct = ((initial_size_mb - size_mb) / initial_size_mb) * 100 if initial_size_mb > 0 else 0
            table.add_row("Source Snapshot", f"{initial_size_mb:.2f} MB", "—")
            table.add_row("Pruned Production DB", f"{size_mb:.2f} MB", f"-{reduction_pct:.1f}% ({initial_size_mb - size_mb:.1f} MB saved)")
            console.print(table)
            console.print(f"\n[bold green]✓ Production snapshot deployed:[/bold green] [white]{PROD_DB}[/white]\n")
        else:
            print(f"Production snapshot ready: {PROD_DB} ({size_mb:.2f} MB)")
    except Exception as e:
        if temp_prod.exists():
            os.remove(temp_prod)
        raise e


if __name__ == "__main__":
    create_production_snapshot()