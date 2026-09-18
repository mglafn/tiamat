import os
import sys
import shutil
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
PROD_DB = BASE_DIR / "data" / "mtg_prices.duckdb"
TEMP_SRC_DB = BASE_DIR / "data" / "mtg_prices_unpruned_tmp.duckdb"


def create_production_snapshot():
    # Detect if there's a stale FULL_DB causing issues and warn about it
    legacy_full_db = BASE_DIR / "data" / "mtg_prices_full.duckdb"
    if legacy_full_db.exists():
        if HAS_RICH:
            console.print(f"[bold yellow]Warning:[/bold yellow] Found stale {legacy_full_db.name}. Ignoring it to prevent schema regression.")
    
    if not PROD_DB.exists():
        if HAS_RICH:
            console.print(f"[bold red]Error:[/bold red] Active database not found at [yellow]{PROD_DB}[/yellow]")
        else:
            print(f"Active database not found at {PROD_DB}", file=sys.stderr)
        sys.exit(1)

    initial_size_mb = PROD_DB.stat().st_size / (1024 * 1024)

    if HAS_RICH:
        console.print(
            Panel(
                f"[bold white]DuckDB Snapshot Pruning Engine (<50MB Budget Target)[/bold white]\n"
                f"[dim]Source: {PROD_DB} ({initial_size_mb:.2f} MB)[/dim]",
                box=box.ROUNDED,
                border_style="cyan",
            )
        )

    # 1. Safely move the active DB to a temporary source file
    if TEMP_SRC_DB.exists():
        os.remove(TEMP_SRC_DB)
    shutil.move(str(PROD_DB), str(TEMP_SRC_DB))

    # 2. Connect to what will become the NEW lightweight PROD_DB
    conn = duckdb.connect(
        str(PROD_DB),
        config={
            "max_memory": "1.5GB",
            "threads": "2",
            "preserve_insertion_order": "false",
        },
    )

    try:
        conn.execute(f"ATTACH '{TEMP_SRC_DB.as_posix()}' AS src (READ_ONLY);")

        conn.execute(
            """
            CREATE OR REPLACE TYPE price_format AS ENUM ('paper', 'mtgo');
            CREATE OR REPLACE TYPE price_vendor AS ENUM ('tcgplayer', 'cardkingdom', 'cardmarket', 'cardsphere', 'starcitygames', 'cardhoarder', 'manapool');
            CREATE OR REPLACE TYPE price_list_type AS ENUM ('retail', 'buylist');
        """
        )

        # Keep ALL active arbitrage opportunities (Cast finish to VARCHAR to prevent orphaned ENUMs)
        conn.execute(
            """
            CREATE TABLE fact_arbitrage_opportunities AS
            SELECT * EXCLUDE (finish), CAST(finish AS VARCHAR) AS finish 
            FROM src.fact_arbitrage_opportunities;
        """
        )

        # Target universe: Top 700 EDHREC staples + Reserved List + All Arb Cards
        conn.execute(
            """
            CREATE TEMP TABLE target_tracked_cards AS
            SELECT DISTINCT uuid FROM src.fact_arbitrage_opportunities
            UNION
            SELECT uuid FROM src.dim_cards
            WHERE (edhrec_rank IS NOT NULL AND edhrec_rank <= 700)
               OR is_reserved = true;
        """
        )

        # Features: 14 days rolling window for tracked cards (saving ~35% row volume)
        conn.execute(
            """
            CREATE TABLE fact_card_features AS
            SELECT f.* EXCLUDE (finish), CAST(f.finish AS VARCHAR) AS finish 
            FROM src.fact_card_features f
            JOIN target_tracked_cards t ON f.uuid = t.uuid
            WHERE f.price_date >= (SELECT MAX(price_date) - INTERVAL 14 DAY FROM src.fact_card_features);
        """
        )

        # Enriched Dimension Table (tracked cards only)
        conn.execute(
            """
            CREATE TABLE dim_cards AS
            SELECT
                d.uuid, d.name, d.set_code, d.collector_number, d.rarity,
                d.edhrec_rank, d.is_online_only, d.is_reserved, d.mana_value,
                d.card_type, d.original_release_date
            FROM src.dim_cards d
            WHERE d.is_online_only = false
              AND d.uuid IN (SELECT DISTINCT uuid FROM target_tracked_cards);
        """
        )

        # Latest Retail Price points for fast lookups
        conn.execute(
            """
            CREATE TABLE fact_prices AS
            WITH ranked_prices AS (
                SELECT
                    uuid, format, vendor, list_type, CAST(finish AS VARCHAR) AS finish, price_date, price,
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
        """
        )

        # Lean essential indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_name ON dim_cards(name);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_uuid ON dim_cards(uuid);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_arb_spread ON fact_arbitrage_opportunities(price_spread DESC);")

        conn.execute("CHECKPOINT;")
        conn.execute("VACUUM;")
        conn.execute("DETACH src;")
        conn.close()

        # Clean up the unpruned temp source file
        if TEMP_SRC_DB.exists():
            os.remove(TEMP_SRC_DB)

        size_mb = PROD_DB.stat().st_size / (1024 * 1024)

        if HAS_RICH:
            table = Table(
                box=box.ROUNDED,
                border_style="green",
                show_header=True,
                header_style="bold green",
            )
            table.add_column("Database Stage", style="bold white")
            table.add_column("Size", justify="right", style="cyan")
            table.add_column("Compression Delta", justify="right", style="bold green")
            reduction_pct = (
                ((initial_size_mb - size_mb) / initial_size_mb) * 100
                if initial_size_mb > 0
                else 0
            )
            table.add_row("Source Snapshot", f"{initial_size_mb:.2f} MB", "—")
            table.add_row(
                "Pruned Production DB",
                f"{size_mb:.2f} MB",
                f"-{reduction_pct:.1f}% ({initial_size_mb - size_mb:.1f} MB saved)",
            )
            console.print(table)
            console.print(
                f"\n[bold green]✓ Lightweight (<50MB) production snapshot deployed:[/bold green] [white]{PROD_DB}[/white]\n"
            )
        else:
            print(f"Production snapshot ready: {PROD_DB} ({size_mb:.2f} MB)")

    except Exception as e:
        # Rollback safely if something breaks
        conn.close()
        if TEMP_SRC_DB.exists():
            if PROD_DB.exists():
                os.remove(PROD_DB)
            shutil.move(str(TEMP_SRC_DB), str(PROD_DB))
        raise e


if __name__ == "__main__":
    create_production_snapshot()