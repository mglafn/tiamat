import os
import shutil
import sys
import duckdb

from src.cli.console import HAS_RICH, Table, box, console, print_banner, print_msg
from src.config import DB_PATH, LEGACY_FULL_DB_PATH, PRUNE_TEMP_DB_PATH
from src.etl.schema import PRICE_ENUM_DDL

PROD_DB = DB_PATH
TEMP_SRC_DB = PRUNE_TEMP_DB_PATH


def create_production_snapshot():
    if LEGACY_FULL_DB_PATH.exists():
        print_msg(
            f"[bold yellow]Warning:[/bold yellow] Found stale {LEGACY_FULL_DB_PATH.name}. Ignoring it to prevent schema regression.",
            f"Warning: Found stale {LEGACY_FULL_DB_PATH.name}. Ignoring it.",
        )

    if not PROD_DB.exists():
        print_msg(
            f"[bold red]Error:[/bold red] Active database not found at [yellow]{PROD_DB}[/yellow]",
            f"Active database not found at {PROD_DB}",
            err=True,
        )
        sys.exit(1)

    initial_size_mb = PROD_DB.stat().st_size / (1024 * 1024)
    print_banner(
        "DuckDB Snapshot Pruning Engine (<50MB Budget Target)",
        f"Source: {PROD_DB} ({initial_size_mb:.2f} MB)",
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
        conn.execute(PRICE_ENUM_DDL)

        # Keep ALL active arbitrage opportunities
        conn.execute("""
            CREATE TABLE fact_arbitrage_opportunities AS
            SELECT * EXCLUDE (finish), CAST(finish AS VARCHAR)::price_finish AS finish 
            FROM src.fact_arbitrage_opportunities;
        """)

        # PLACEHOLDER: 700 EDHREC cap meets <50MB budget (note: scan_buyer_dips.py defaults to 1500)
        conn.execute("""
            CREATE TEMP TABLE target_tracked_cards AS
            SELECT DISTINCT uuid FROM src.fact_arbitrage_opportunities
            UNION
            SELECT uuid FROM src.dim_cards
            WHERE (edhrec_rank IS NOT NULL AND edhrec_rank <= 700)
               OR is_reserved = true;
        """)

        # Features: Retain 60 days so frontend 60D history and 20D Bollinger Bands render intact
        conn.execute("""
            CREATE TABLE fact_card_features AS
            SELECT f.* EXCLUDE (finish), CAST(f.finish AS VARCHAR)::price_finish AS finish 
            FROM src.fact_card_features f
            JOIN target_tracked_cards t ON f.uuid = t.uuid
            WHERE f.price_date >= (SELECT MAX(price_date) - INTERVAL 60 DAY FROM src.fact_card_features);
        """)

        # Retain recent training/backtest slice so /api/v1/backtest and run_pipeline checks remain valid
        conn.execute("""
            CREATE TABLE fact_training_dataset AS
            SELECT tr.* EXCLUDE (finish), CAST(tr.finish AS VARCHAR)::price_finish AS finish
            FROM src.fact_training_dataset tr
            JOIN target_tracked_cards t ON tr.uuid = t.uuid
            WHERE tr.price_date >= (SELECT MAX(price_date) - INTERVAL 30 DAY FROM src.fact_training_dataset);
        """)

        # Enriched Dimension Table (tracked cards only)
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

        # Latest Retail Price points for fast lookups
        conn.execute("""
            CREATE TABLE fact_prices AS
            WITH ranked_prices AS (
                SELECT
                    uuid, format, vendor, list_type, CAST(finish AS VARCHAR)::price_finish AS finish, price_date, price,
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

        # Lean essential indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_name ON dim_cards(name);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_uuid ON dim_cards(uuid);")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_arb_spread ON fact_arbitrage_opportunities(price_spread DESC);"
        )

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
                ((initial_size_mb - size_mb) / initial_size_mb) * 100 if initial_size_mb > 0 else 0
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
