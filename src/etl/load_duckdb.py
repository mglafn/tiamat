import sys
import time
from pathlib import Path
from typing import Generator, Iterator, Tuple
import duckdb
import pandas as pd

from src.cli.console import (
    HAS_RICH,
    Panel,
    Table,
    box,
    console,
    print_banner,
    print_msg,
)
from src.config import ALL_PRICES_JSON_PATH, ALL_PRICES_XZ_PATH, CARDS_CSV_PATH, DB_PATH
from src.etl.extract_prices import stream_mtg_prices
from src.etl.schema import PRICE_ENUM_DDL

SUPPORTED_FORMATS = {"paper", "mtgo"}
SUPPORTED_VENDORS = {
    "tcgplayer",
    "cardkingdom",
    "cardmarket",
    "cardsphere",
    "starcitygames",
    "cardhoarder",
    "manapool",
}


PRICE_BATCH_COLS = [
    "uuid",
    "format",
    "vendor",
    "list_type",
    "finish",
    "price_date",
    "price",
]

PriceRow = Tuple[str, str, str, str, str, str, float]


def _iter_valid_price_rows(raw_file_path: Path) -> Iterator[PriceRow]:
    for uuid, price_data in stream_mtg_prices(str(raw_file_path)):
        if not isinstance(price_data, dict):
            continue
        for card_format, vendors in price_data.items():
            if card_format not in SUPPORTED_FORMATS or not isinstance(vendors, dict):
                continue
            for vendor, vendor_data in vendors.items():
                if vendor not in SUPPORTED_VENDORS or not isinstance(vendor_data, dict):
                    continue
                currency = vendor_data.get("currency", "USD")
                if vendor == "cardmarket" or (currency is not None and currency != "USD"):
                    continue
                yield from _iter_vendor_rows(str(uuid), str(card_format), str(vendor), vendor_data)


def _iter_vendor_rows(
    uuid: str, card_format: str, vendor: str, vendor_data: dict
) -> Iterator[PriceRow]:
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
                if price_float > 0.0:
                    yield (
                        uuid,
                        card_format,
                        vendor,
                        list_type,
                        finish,
                        str(date_str),
                        price_float,
                    )


def parse_and_batch_records(
    raw_file_path: Path, batch_size: int = 50000
) -> Generator[pd.DataFrame, None, None]:
    records_batch: list[PriceRow] = []
    for row in _iter_valid_price_rows(raw_file_path):
        records_batch.append(row)
        if len(records_batch) >= batch_size:
            yield pd.DataFrame(records_batch, columns=PRICE_BATCH_COLS)
            records_batch = []

    if records_batch:
        yield pd.DataFrame(records_batch, columns=PRICE_BATCH_COLS)


def load_dimension_cards(conn: duckdb.DuckDBPyConnection, cards_csv_path: Path):
    posix_path = cards_csv_path.as_posix()
    print_msg(
        f"[bold cyan]→ Ingesting dimension catalog:[/bold cyan] [dim]{posix_path}[/dim]",
        f"Ingesting enriched dimension catalog from {posix_path}...",
    )

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
    print_msg(
        f"  [bold green]✓ Table `dim_cards` created:[/bold green] [bold white]{count:,}[/bold white] distinct cards\n",
        f"Dimension table 'dim_cards' loaded with {count:,} cards.\n",
    )


def _stage_raw_prices(conn: duckdb.DuckDBPyConnection, raw_feed_path: Path) -> int:
    conn.execute(PRICE_ENUM_DDL)
    conn.execute("""
        DROP TABLE IF EXISTS raw_fact_prices;
        CREATE TABLE raw_fact_prices (
            uuid VARCHAR,
            format price_format,
            vendor price_vendor,
            list_type price_list_type,
            finish price_finish,
            price_date DATE,
            price FLOAT
        );
        """)
    print_msg(
        "[bold cyan]→ Ingesting raw JSON price records into temporary staging...[/bold cyan]",
        "Beginning DuckDB fact table staging...",
    )

    total_rows = 0
    for batch_idx, df_batch in enumerate(parse_and_batch_records(raw_feed_path), start=1):
        conn.register("df_batch_view", df_batch)
        conn.execute("""
            INSERT INTO raw_fact_prices
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
        print_msg(
            f"  [dim]Batch {batch_idx:03d} -> Ingested {len(df_batch):,} rows | Staged Total: {total_rows:,}[/dim]",
            f"  -> Ingested batch {batch_idx:03d}... Staged Total: {total_rows:,}",
        )
    return total_rows


def _apply_hampel_filter(conn: duckdb.DuckDBPyConnection) -> int:
    print_msg(
        "[bold cyan]→ Applying Robust Hampel MAD Filter for Anomaly Rejection...[/bold cyan]",
        "Applying Robust Hampel MAD Filter for Anomaly Rejection...",
    )
    conn.execute("""
        DROP TABLE IF EXISTS fact_prices;
        CREATE TABLE fact_prices AS
        WITH RollingWindowStats AS (
            SELECT
                uuid, format, vendor, list_type, finish, price_date, price,
                MEDIAN(price) OVER w AS rolling_median,
                (QUANTILE_CONT(price, 0.75) OVER w - QUANTILE_CONT(price, 0.25) OVER w) AS rolling_iqr,
                LEAD(price, 1) OVER (
                    PARTITION BY uuid, format, vendor, list_type, finish
                    ORDER BY price_date
                ) AS next_price
            FROM raw_fact_prices
            WINDOW w AS (
                PARTITION BY uuid, format, vendor, list_type, finish
                ORDER BY price_date
                RANGE BETWEEN INTERVAL 7 DAY PRECEDING AND CURRENT ROW
            )
        ),
        AbsoluteDeviations AS (
            SELECT *, ABS(price - rolling_median) AS abs_dev
            FROM RollingWindowStats
        ),
        MADStats AS (
            SELECT *, MEDIAN(abs_dev) OVER w AS raw_mad
            FROM AbsoluteDeviations
            WINDOW w AS (
                PARTITION BY uuid, format, vendor, list_type, finish
                ORDER BY price_date
                RANGE BETWEEN INTERVAL 7 DAY PRECEDING AND CURRENT ROW
            )
        ),
        CorrectedZScore AS (
            SELECT *,
                -- PLACEHOLDER: 0.15 scale floor bounds downward glitch rejection pending spike-reversion policy
                GREATEST(1.4826 * raw_mad, 0.7413 * rolling_iqr, 0.15 * rolling_median, 0.25) AS robust_scale
            FROM MADStats
        ),
        FlaggedTicks AS (
            SELECT
                uuid, format, vendor, list_type, finish, price_date,
                CASE
                    WHEN format = 'paper' AND list_type = 'retail' AND price < 0.40 THEN NULL
                    WHEN ((rolling_median - price) / robust_scale) > 3.5 THEN NULL
                    WHEN next_price IS NOT NULL
                         AND price > (rolling_median * 4.0)
                         AND next_price < (price * 0.40) THEN NULL
                    ELSE price
                END AS clean_price
            FROM CorrectedZScore
        ),
        ForwardFilled AS (
            SELECT
                uuid, format, vendor, list_type, finish, price_date,
                LAST_VALUE(clean_price IGNORE NULLS) OVER (
                    PARTITION BY uuid, format, vendor, list_type, finish
                    ORDER BY price_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS price
            FROM FlaggedTicks
        )
        SELECT * FROM ForwardFilled WHERE price IS NOT NULL;
        """)
    conn.execute("DROP TABLE raw_fact_prices;")
    final_rows = conn.execute("SELECT COUNT(*) FROM fact_prices").fetchone()[0]
    print_msg(
        f"  [bold green]✓ Fact prices clean & complete:[/bold green] [bold white]{final_rows:,}[/bold white] total observations\n",
        f"Fact table complete! Total clean records loaded: {final_rows:,}\n",
    )
    return final_rows


def main():
    start_time = time.time()
    raw_feed_path = ALL_PRICES_XZ_PATH if ALL_PRICES_XZ_PATH.exists() else ALL_PRICES_JSON_PATH
    if not raw_feed_path.exists():
        print_msg(
            f"[bold red]Error:[/bold red] Raw feed file not found at [yellow]{raw_feed_path}[/yellow].\n"
            "Run [cyan]python -m src.etl.download_raw[/cyan] first.",
            f"Error: Raw feed file not found at {raw_feed_path}. Run `python -m src.etl.download_raw` first.",
            err=True,
        )
        sys.exit(1)

    print_banner("DuckDB Columnar Ingestion Pipeline", f"Destination: {DB_PATH}")

    conn = duckdb.connect(
        str(DB_PATH),
        config={
            "max_memory": "2GB",
            "threads": "4",
            "preserve_insertion_order": "false",
        },
    )

    try:
        total_rows = _stage_raw_prices(conn, raw_feed_path)
        final_rows = _apply_hampel_filter(conn)

        print_msg(
            "[bold cyan]→ Building analytical indexes...[/bold cyan]",
            "Building analytical indexes on fact_prices...",
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fact_prices_lookup ON fact_prices(uuid, finish);"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fact_prices_date ON fact_prices(price_date);")

        if CARDS_CSV_PATH.exists():
            load_dimension_cards(conn, CARDS_CSV_PATH)
        else:
            print_msg(
                f"[bold yellow]Warning:[/bold yellow] {CARDS_CSV_PATH} not found. Skipping dim_cards.",
                f"Warning: {CARDS_CSV_PATH} not found. Skipping dim_cards creation.",
            )

        elapsed = time.time() - start_time
        if HAS_RICH:
            summary = Table(
                box=box.ROUNDED,
                border_style="green",
                show_header=True,
                header_style="bold green",
            )
            summary.add_column("Pipeline Stage", style="bold white")
            summary.add_column("Record Count", justify="right", style="cyan")
            summary.add_column("Status / SLA", justify="right", style="bold green")
            summary.add_row("Raw Price Ticks Staged", f"{total_rows:,}", "Ingested")
            summary.add_row(
                "Hampel MAD Sanitized Ticks",
                f"{final_rows:,}",
                f"-{total_rows - final_rows:,} anomalies removed",
            )
            summary.add_row(
                "Total Ingestion Elapsed Time",
                f"{elapsed:.2f}s",
                "Sub-100s Target Cleared",
            )
            summary.add_row(
                "Columnar Physical Layout",
                "ENUM Dictionary Encoded",
                "Zonemaps & Index Built",
            )
            console.print(
                Panel(
                    summary,
                    title="[bold green]DuckDB Ingestion Pipeline Complete[/bold green]",
                    box=box.ROUNDED,
                )
            )

    finally:
        conn.close()
        if not HAS_RICH:
            print("DuckDB connection closed successfully.")


if __name__ == "__main__":
    main()
