import os
import sys
import time
from pathlib import Path
from typing import Generator
import duckdb
import pandas as pd

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "src" / "etl"))

try:
    from extract_prices import stream_mtg_prices
except ImportError:
    from src.etl.extract_prices import stream_mtg_prices


def parse_and_batch_records(raw_file_path: Path, batch_size: int = 50000) -> Generator[pd.DataFrame, None, None]:
    records_batch = []
    for uuid, price_data in stream_mtg_prices(str(raw_file_path)):
        if not isinstance(price_data, dict):
            continue
        for card_format, vendors in price_data.items():
            if not isinstance(vendors, dict):
                continue
            for vendor, vendor_data in vendors.items():
                if not isinstance(vendor_data, dict):
                    continue
                for list_type in ("retail", "buylist"):
                    list_data = vendor_data.get(list_type)
                    if not isinstance(list_data, dict):
                        continue
                    for finish in ("normal", "foil", "etched"):
                        date_prices = list_data.get(finish)
                        if not isinstance(date_prices, dict):
                            continue
                        for date_str, price in date_prices.items():
                            try:
                                price_float = float(price)
                            except (ValueError, TypeError):
                                continue
                            if price_float <= 0.0:
                                continue
                            records_batch.append((
                                str(uuid),
                                str(card_format),
                                str(vendor),
                                str(list_type),
                                str(finish),
                                str(date_str),
                                price_float
                            ))
                            if len(records_batch) >= batch_size:
                                df = pd.DataFrame(
                                    records_batch,
                                    columns=["uuid", "format", "vendor", "list_type", "finish", "price_date", "price"]
                                )
                                yield df
                                records_batch = []
    if records_batch:
        df = pd.DataFrame(
            records_batch,
            columns=["uuid", "format", "vendor", "list_type", "finish", "price_date", "price"]
        )
        yield df


def load_dimension_cards(conn: duckdb.DuckDBPyConnection, cards_csv_path: Path):
    posix_path = cards_csv_path.as_posix()
    if HAS_RICH:
        console.print(f"[bold cyan]→ Ingesting dimension catalog:[/bold cyan] [dim]{posix_path}[/dim]")
    else:
        print(f"Ingesting enriched dimension catalog from {posix_path}...")

    conn.execute("DROP TABLE IF EXISTS dim_cards")
    conn.execute(f"""
        CREATE TABLE dim_cards AS
        SELECT
            uuid,
            name,
            COALESCE(setCode, 'OTC') AS set_code,
            number AS collector_number,
            rarity,
            TRY_CAST(edhrecRank AS INTEGER) AS edhrec_rank,
            COALESCE(TRY_CAST(isOnlineOnly AS BOOLEAN), false) AS is_online_only,
            COALESCE(TRY_CAST(isReserved AS BOOLEAN), false) AS is_reserved,
            COALESCE(TRY_CAST(manaValue AS DOUBLE), 0.0) AS mana_value,
            COALESCE(types, 'Unknown') AS card_type,
            TRY_CAST(originalReleaseDate AS DATE) AS original_release_date
        FROM read_csv_auto('{posix_path}', header=true, ignore_errors=true)
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_name ON dim_cards(name);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_cards_uuid ON dim_cards(uuid);")
    count = conn.execute("SELECT COUNT(*) FROM dim_cards").fetchone()[0]
    
    if HAS_RICH:
        console.print(f"  [bold green]✓ Table `dim_cards` created:[/bold green] [bold white]{count:,}[/bold white] distinct cards\n")
    else:
        print(f"Dimension table 'dim_cards' loaded with {count:,} cards.\n")


def main():
    start_time = time.time()
    raw_dir = BASE_DIR / "data" / "raw"
    db_dir = BASE_DIR / "data"
    raw_dir.mkdir(parents=True, exist_ok=True)
    db_dir.mkdir(parents=True, exist_ok=True)

    raw_feed_path = raw_dir / "AllPrices.json.xz"
    if not raw_feed_path.exists():
        raw_feed_path = raw_dir / "AllPrices.json"
    cards_csv_path = raw_dir / "cards.csv"
    db_path = db_dir / "mtg_prices.duckdb"

    if not raw_feed_path.exists():
        if HAS_RICH:
            console.print(f"[bold red]Error:[/bold red] Raw feed file not found at [yellow]{raw_feed_path}[/yellow].")
            console.print("Run [cyan]python src/etl/download_raw.py[/cyan] first.")
        else:
            print(f"Error: Raw feed file not found at {raw_feed_path}.")
            print("Please run `python src/etl/download_raw.py` first.")
        sys.exit(1)

    if HAS_RICH:
        console.print(Panel(
            f"[bold white]DuckDB Columnar Ingestion Pipeline[/bold white]\n"
            f"[dim]Destination: {db_path}[/dim]",
            box=box.ROUNDED,
            border_style="cyan"
        ))
    else:
        print(f"Connecting to DuckDB at: {db_path}")

    conn = duckdb.connect(str(db_path), config={
        'max_memory': '2GB',
        'threads': '4',
        'preserve_insertion_order': 'false'
    })

    try:
        conn.execute("""
            CREATE TYPE price_format AS ENUM ('paper', 'mtgo');
            CREATE TYPE price_vendor AS ENUM ('tcgplayer', 'cardkingdom', 'cardmarket', 'cardsphere', 'starcitygames', 'cardhoarder', 'manapool');
            CREATE TYPE price_list_type AS ENUM ('retail', 'buylist');
            CREATE TYPE price_finish AS ENUM ('normal', 'foil', 'etched');
            DROP TABLE IF EXISTS fact_prices;
            CREATE TABLE fact_prices (
                uuid VARCHAR,
                format price_format,
                vendor price_vendor,
                list_type price_list_type,
                finish price_finish,
                price_date DATE,
                price FLOAT
            );
        """)

        if HAS_RICH:
            console.print("[bold cyan]→ Ingesting raw JSON price records into DuckDB `fact_prices`...[/bold cyan]")
        else:
            print("Beginning DuckDB fact table ingestion...")

        total_rows = 0
        batch_idx = 0
        for df_batch in parse_and_batch_records(raw_feed_path):
            conn.register("df_batch_view", df_batch)
            conn.execute("""
                INSERT INTO fact_prices
                SELECT
                    uuid,
                    format::price_format,
                    vendor::price_vendor,
                    list_type::price_list_type,
                    finish::price_finish,
                    CAST(price_date AS DATE),
                    CAST(price AS FLOAT)
                FROM df_batch_view
            """)
            conn.unregister("df_batch_view")
            total_rows += len(df_batch)
            batch_idx += 1
            if HAS_RICH:
                console.print(f"  [dim]Batch #{batch_idx:03d} │ Ingested {len(df_batch):,} rows │ Total: [bold white]{total_rows:,}[/bold white][/dim]")
            else:
                print(f"  -> Ingested batch... Total records loaded: {total_rows:,}")

        if HAS_RICH:
            console.print(f"  [bold green]✓ Fact prices complete:[/bold green] [bold white]{total_rows:,}[/bold white] total observations\n")
            console.print("[bold cyan]→ Building analytical indexes...[/bold cyan]")
        else:
            print(f"Fact table complete! Total records loaded: {total_rows:,}\n")
            print("Building analytical indexes on fact_prices...")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_fact_prices_lookup ON fact_prices(uuid, finish);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fact_prices_date ON fact_prices(price_date);")

        if cards_csv_path.exists():
            load_dimension_cards(conn, cards_csv_path)
        else:
            if HAS_RICH:
                console.print(f"[bold yellow]Warning:[/bold yellow] {cards_csv_path} not found. Skipping dim_cards.")
            else:
                print(f"Warning: {cards_csv_path} not found. Skipping dim_cards creation.")

        elapsed = time.time() - start_time
        if HAS_RICH:
            summary = Table(box=box.ROUNDED, border_style="green", show_header=False)
            summary.add_column("Metric", style="dim")
            summary.add_column("Value", style="bold white")
            summary.add_row("Total Price Rows", f"{total_rows:,}")
            summary.add_row("Execution Time", f"{elapsed:.2f}s")
            summary.add_row("Database Status", "Ready (Indexed)")
            console.print(Panel(summary, title="[bold green]DuckDB Ingestion Complete[/bold green]", box=box.ROUNDED))
    finally:
        conn.close()
        if not HAS_RICH:
            print("DuckDB connection closed successfully.")


if __name__ == "__main__":
    main()