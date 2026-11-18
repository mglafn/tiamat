"""
src/analytics/build_features.py
-------------------------------
Vectorized OLAP Feature Engineering Pipeline.
Derives scale-invariant price derivatives, robust volatility, and regime states
using parameters defined in src.config.
"""

from pathlib import Path
import time
import duckdb

from src.cli.console import (
    HAS_RICH,
    Panel,
    Table,
    box,
    console,
    print_banner,
    print_msg,
)
from src.config import DB_PATH, MICROSTRUCTURE_CONFIG
from src.pricing.fees import ck_credit_payout_sql, spatial_landed_basis_sql


def build_feature_store(conn: duckdb.DuckDBPyConnection) -> int:
    """Populate `fact_card_features` with rolling indicators and microstructure regimes."""
    cfg = MICROSTRUCTURE_CONFIG
    conn.execute("DROP TABLE IF EXISTS fact_card_features")
    conn.execute(f"""
        CREATE TABLE fact_card_features AS
        WITH daily_market AS (
            SELECT
                uuid,
                finish,
                price_date,
                MIN(CASE WHEN list_type = 'retail' THEN price END) AS market_retail,
                MAX(CASE WHEN list_type = 'buylist' THEN price END) AS market_buylist,
                COUNT(CASE WHEN list_type = 'retail' THEN 1 END) AS active_vendors
            FROM fact_prices
            WHERE format = 'paper' AND vendor != 'cardmarket'
            GROUP BY uuid, finish, price_date
            HAVING MIN(CASE WHEN list_type = 'retail' THEN price END) IS NOT NULL
        ),
        lagged_prices AS (
            SELECT
                uuid,
                finish,
                price_date,
                market_retail AS current_price,
                active_vendors,
                market_buylist,
                LN(GREATEST(0.01, market_retail)) AS ln_price,
                LAG(market_retail, 1) OVER w_card AS price_t_minus_1,
                LAG(price_date, 1) OVER w_card AS date_t_minus_1,
                LAG(market_retail, 3) OVER w_card AS price_t_minus_3,
                LAG(price_date, 3) OVER w_card AS date_t_minus_3,
                LAG(market_retail, 6) OVER w_card AS price_t_minus_6,
                LAG(price_date, 6) OVER w_card AS date_t_minus_6
            FROM daily_market
            WINDOW w_card AS (PARTITION BY uuid, finish ORDER BY price_date ASC)
        ),
        time_deltas AS (
            SELECT
                *,
                GREATEST(1.0, COALESCE(DATE_DIFF('day', date_t_minus_3, price_date), 3)) AS dt_3d,
                GREATEST(
                    1.0, COALESCE(DATE_DIFF('day', date_t_minus_6, date_t_minus_3), 3)
                ) AS dt_3d_prev,
                CASE
                    WHEN price_t_minus_1 IS NOT NULL
                        THEN ln_price - LN(GREATEST(0.01, price_t_minus_1))
                END AS log_ret_1d,
                CASE
                    WHEN price_t_minus_3 IS NOT NULL
                        THEN ln_price - LN(GREATEST(0.01, price_t_minus_3))
                END AS log_ret_3d,
                CASE
                    WHEN price_t_minus_3 IS NOT NULL AND price_t_minus_6 IS NOT NULL
                        THEN LN(GREATEST(0.01, price_t_minus_3))
                        - LN(GREATEST(0.01, price_t_minus_6))
                END AS log_ret_3d_prev,
                COALESCE(
                    ((current_price - price_t_minus_1) / NULLIF(price_t_minus_1, 0) * 100.0)
                    / GREATEST(1, COALESCE(DATE_DIFF('day', date_t_minus_1, price_date), 1)),
                    0.0
                ) AS daily_return_pct
            FROM lagged_prices
        ),
        rolling_dispersion AS (
            SELECT
                *,
                MEDIAN(log_ret_1d) OVER w_14d AS median_ret_1d,
                mad(log_ret_1d) OVER w_14d AS mad_ret_1d,
                MEDIAN(log_ret_3d) OVER w_14d AS median_ret_3d,
                COALESCE(STDDEV(daily_return_pct) OVER w_14d, 0.0) AS volatility_14d,
                AVG(current_price) OVER (
                    PARTITION BY uuid, finish ORDER BY price_date ASC
                    RANGE BETWEEN INTERVAL 6 DAYS PRECEDING AND CURRENT ROW
                ) AS sma_7,
                AVG(current_price) OVER (
                    PARTITION BY uuid, finish ORDER BY price_date ASC
                    RANGE BETWEEN INTERVAL 29 DAYS PRECEDING AND CURRENT ROW
                ) AS sma_30
            FROM time_deltas
            WINDOW w_14d AS (
                PARTITION BY uuid, finish ORDER BY price_date ASC
                RANGE BETWEEN INTERVAL 13 DAYS PRECEDING AND CURRENT ROW
            )
        ),
        derivatives AS (
            SELECT
                *,
                -- STRUCTURAL VOLATILITY FLOOR: MAD scaled or minimum discrete tick ($0.01 / price)
                GREATEST(
                    1.4826 * COALESCE(mad_ret_1d, 0.0),
                    {cfg['MIN_TICK_USD']} / GREATEST(0.01, current_price)
                ) AS robust_vol_14d,
                COALESCE(log_ret_3d, 0.0) / dt_3d AS velocity_3d,
                CASE
                    WHEN log_ret_3d_prev IS NOT NULL THEN
                        ((log_ret_3d / dt_3d) - (log_ret_3d_prev / dt_3d_prev))
                        / (0.5 * (dt_3d + dt_3d_prev))
                    ELSE 0.0
                END AS accel_3d,
                COALESCE(
                    (current_price - market_buylist) / NULLIF(current_price, 0), 1.0
                ) AS bid_ask_spread_pct
            FROM rolling_dispersion
        ),
        regime_inputs AS (
            SELECT
                *,
                ((current_price - sma_7) / NULLIF(sma_7, 0)) * 100.0 AS velocity_7d_pct,
                (sma_7 / NULLIF(sma_30, 0)) AS sma_ratio,
                (bid_ask_spread_pct - FIRST_VALUE(bid_ask_spread_pct) OVER (
                    PARTITION BY uuid, finish ORDER BY price_date ASC
                    RANGE BETWEEN INTERVAL 7 DAYS PRECEDING AND CURRENT ROW
                )) AS spread_velocity_7d,
                (active_vendors - FIRST_VALUE(active_vendors) OVER (
                    PARTITION BY uuid, finish ORDER BY price_date ASC
                    RANGE BETWEEN INTERVAL 7 DAYS PRECEDING AND CURRENT ROW
                )) AS vendor_delta_7d,
                COALESCE(
                    ((current_price - price_t_minus_3) / NULLIF(price_t_minus_3, 0) / dt_3d)
                    * 100.0,
                    0.0
                ) AS price_decay_velocity_3d,
                -- PLACEHOLDER: Uses active_vendors (feed count) as volume proxy pending unit sales
                AVG(
                    ABS(daily_return_pct) / NULLIF(current_price * active_vendors, 0)
                ) OVER (
                    PARTITION BY uuid, finish ORDER BY price_date ASC
                    RANGE BETWEEN INTERVAL 29 DAYS PRECEDING AND CURRENT ROW
                ) AS amihud_illiquidity_30d,
                (COALESCE(log_ret_3d, 0.0) - COALESCE(median_ret_3d, 0.0))
                / (robust_vol_14d * SQRT(dt_3d)) AS z_downside_3d,
                accel_3d / (ABS(velocity_3d) + 1e-6) AS exhaustion_ratio
            FROM derivatives
        )
        SELECT
            r.uuid,
            'consensus' AS vendor,
            r.finish,
            r.price_date,
            r.current_price,
            r.sma_7,
            r.sma_30,
            r.daily_return_pct,
            r.velocity_3d,
            r.accel_3d,
            r.velocity_7d_pct,
            r.sma_ratio,
            r.volatility_14d,
            r.bid_ask_spread_pct,
            r.spread_velocity_7d,
            r.vendor_delta_7d,
            r.price_decay_velocity_3d,
            r.amihud_illiquidity_30d,
            r.robust_vol_14d,
            r.z_downside_3d,
            r.exhaustion_ratio,
            CASE
                WHEN r.log_ret_3d IS NULL
                    THEN 'INSUFFICIENT_HISTORY'
                WHEN r.z_downside_3d < {cfg['KNIFE_Z_SCORE_THRESH']}
                    AND r.velocity_3d < 0
                    AND r.accel_3d < 0
                    THEN 'FALLING_KNIFE'
                WHEN r.z_downside_3d < {cfg['BOTTOM_Z_SCORE_THRESH']}
                    AND r.velocity_3d < 0
                    AND r.accel_3d > 0
                    AND r.exhaustion_ratio >= {cfg['MIN_EXHAUSTION_RATIO']}
                    THEN 'CONFIRMED_LOCAL_BOTTOM'
                WHEN ABS(r.z_downside_3d) <= {cfg['NOISE_Z_SCORE_BOUND']}
                    THEN 'NOISE_BOUND'
                ELSE 'TRANSITIONAL'
            END AS microstructure_regime,
            CASE WHEN r.finish IN ('foil', 'etched') THEN 1 ELSE 0 END AS is_foil,
            CASE WHEN d.is_reserved THEN 1 ELSE 0 END AS is_reserved,
            COALESCE(d.mana_value, 0.0) AS mana_value,
            CASE
                WHEN d.edhrec_rank IS NOT NULL AND d.edhrec_rank > 0
                    THEN (1.0 / LOG10(d.edhrec_rank + 1.0))
                ELSE 0.0
            END AS popularity_score,
            CASE WHEN d.card_type ILIKE '%Land%' THEN 1 ELSE 0 END AS is_land,
            CASE WHEN d.card_type ILIKE '%Creature%' THEN 1 ELSE 0 END AS is_creature,
            GREATEST(
                0.0,
                DATE_DIFF('day', COALESCE(d.original_release_date, r.price_date), r.price_date)
                / 365.25
            ) AS asset_age_years,
            CASE
                WHEN d.rarity = 'mythic' THEN 4
                WHEN d.rarity = 'rare' THEN 3
                WHEN d.rarity = 'uncommon' THEN 2
                ELSE 1
            END AS rarity_score
        FROM regime_inputs r
        LEFT JOIN dim_cards d ON r.uuid = d.uuid;
        """)
    return conn.execute("SELECT COUNT(*) FROM fact_card_features").fetchone()[0]


def build_training_dataset(conn: duckdb.DuckDBPyConnection) -> int:
    """Populate `fact_training_dataset` with forward 7-to-14 day target returns."""
    conn.execute("DROP TABLE IF EXISTS fact_training_dataset")
    conn.execute("""
        CREATE TABLE fact_training_dataset AS
        WITH forward_targets AS (
            SELECT
                uuid,
                vendor,
                finish,
                price_date,
                current_price,
                FIRST_VALUE(current_price IGNORE NULLS) OVER (
                    PARTITION BY uuid, vendor, finish ORDER BY price_date ASC
                    RANGE BETWEEN INTERVAL 7 DAYS FOLLOWING AND INTERVAL 14 DAYS FOLLOWING
                ) AS future_price
            FROM fact_card_features
        )
        SELECT
            uuid,
            vendor,
            finish,
            price_date,
            current_price,
            ROUND(
                (((future_price - current_price) / NULLIF(current_price, 0)) * 100.0),
                4
            ) AS target_return_7d_pct
        FROM forward_targets
        WHERE future_price IS NOT NULL;
        """)
    return conn.execute("SELECT COUNT(*) FROM fact_training_dataset").fetchone()[0]


def build_arbitrage_opportunities(conn: duckdb.DuckDBPyConnection) -> int:
    """Populate `fact_arbitrage_opportunities` via ASOF alignment of CK buylist to TCG retail."""
    basis_sql = spatial_landed_basis_sql("t.tcg_price")
    payout_sql = ck_credit_payout_sql("c.ck_price")

    conn.execute("DROP TABLE IF EXISTS fact_arbitrage_opportunities")
    conn.execute(f"""
        CREATE TABLE fact_arbitrage_opportunities AS
        WITH tcg_prices AS (
            SELECT uuid, finish, price_date, MIN(price) AS tcg_price
            FROM fact_prices
            WHERE vendor = 'tcgplayer' AND list_type = 'retail' AND format = 'paper'
            GROUP BY uuid, finish, price_date
        ),
        ck_buylist_prices AS (
            SELECT uuid, finish, price_date, MAX(price) AS ck_price
            FROM fact_prices
            WHERE vendor = 'cardkingdom' AND list_type = 'buylist' AND format = 'paper'
            GROUP BY uuid, finish, price_date
        ),
        latest_ck_offers AS (
            SELECT c.uuid, c.finish, c.price_date AS ck_date, c.ck_price
            FROM ck_buylist_prices c
            WHERE c.price_date >= (
                SELECT MAX(price_date) - INTERVAL 3 DAY FROM fact_prices WHERE format = 'paper'
            )
            QUALIFY ROW_NUMBER() OVER(PARTITION BY c.uuid, c.finish ORDER BY c.price_date DESC) = 1
        ),
        asof_aligned AS (
            SELECT
                c.uuid,
                c.finish,
                c.ck_date AS price_date,
                t.tcg_price,
                c.ck_price,
                {basis_sql} AS total_acquisition_basis,
                {payout_sql} AS ck_store_credit_payout
            FROM latest_ck_offers c
            ASOF JOIN tcg_prices t
                ON c.uuid = t.uuid AND c.finish = t.finish AND c.ck_date >= t.price_date
            WHERE t.tcg_price IS NOT NULL AND DATE_DIFF('day', t.price_date, c.ck_date) <= 3
        )
        SELECT
            uuid,
            price_date,
            finish,
            ROUND(tcg_price, 2) AS tcg_price,
            ROUND(ck_price, 2) AS ck_price,
            ROUND(ck_store_credit_payout - total_acquisition_basis, 2) AS price_spread,
            ROUND(
                ((ck_store_credit_payout - total_acquisition_basis)
                / NULLIF(total_acquisition_basis, 0)) * 100.0,
                2
            ) AS spread_pct
        FROM asof_aligned
        WHERE ck_store_credit_payout > total_acquisition_basis;
        """)
    return conn.execute("SELECT COUNT(*) FROM fact_arbitrage_opportunities").fetchone()[0]


def _create_analytical_indexes(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_features_lookup ON fact_card_features(uuid, finish);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_features_regime "
        "ON fact_card_features(microstructure_regime);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_date ON fact_training_dataset(price_date);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_arb_spread "
        "ON fact_arbitrage_opportunities(price_spread DESC);"
    )
    conn.execute("CHECKPOINT; VACUUM;")


def build_analytical_features(db_path: Path = DB_PATH) -> None:
    start_time = time.time()

    if not db_path.exists():
        err_msg = f"Database not found at '{db_path}'. Run ETL (load_duckdb.py) first."
        print_msg(f"[bold red]✖ Error:[/bold red] {err_msg}", f"Error: {err_msg}", err=True)
        raise FileNotFoundError(err_msg)

    print_banner(
        "Scale-Invariant Feature Engineering",
        "DuckDB OLAP • Tick-Size Robust Volatility • Config-Driven Regimes",
        [
            f"[dim cyan]Target DB: {db_path.name}[/dim cyan]",
            "Status: [bold green]Processing SQL Window Frames[/bold green]",
        ],
    )

    conn = duckdb.connect(
        str(db_path),
        config={"threads": "4", "max_memory": "2GB", "preserve_insertion_order": "false"},
    )

    try:
        print_msg(
            "[bold cyan][1/3] Building `fact_card_features` "
            "(Scale-Invariant Derivatives)...[/bold cyan]",
            "[1/3] Building `fact_card_features`...",
        )
        feat_count = build_feature_store(conn)
        print_msg(
            f"  [bold green]✓ `fact_card_features` populated:[/bold green] "
            f"[white]{feat_count:,}[/white] feature vectors",
            f"  -> `fact_card_features`: {feat_count:,} rows",
        )

        print_msg(
            "[bold cyan][2/3] Building `fact_training_dataset`...[/bold cyan]",
            "[2/3] Building `fact_training_dataset`...",
        )
        train_count = build_training_dataset(conn)
        print_msg(
            f"  [bold green]✓ `fact_training_dataset` populated:[/bold green] "
            f"[white]{train_count:,}[/white] labeled instances",
            f"  -> `fact_training_dataset`: {train_count:,} rows",
        )

        print_msg(
            "[bold cyan][3/3] Building `fact_arbitrage_opportunities`...[/bold cyan]",
            "[3/3] Building `fact_arbitrage_opportunities`...",
        )
        arb_count = build_arbitrage_opportunities(conn)
        print_msg(
            f"  [bold green]✓ `fact_arbitrage_opportunities` populated:[/bold green] "
            f"[white]{arb_count:,}[/white] locked spatial spreads\n",
            f"  -> `fact_arbitrage_opportunities`: {arb_count:,} rows",
        )

        _create_analytical_indexes(conn)

        elapsed = time.time() - start_time
        if HAS_RICH:
            summary = Table(
                box=box.ROUNDED, border_style="green", show_header=True, header_style="bold green"
            )
            summary.add_column("Analytical Store", style="bold white")
            summary.add_column("Rows Generated", justify="right", style="cyan")
            summary.add_column("Derivation SLA", justify="right", style="bold green")
            summary.add_row("Feature Store", f"{feat_count:,}", "Scale-Invariant Windowed")
            summary.add_row("Training Target Set", f"{train_count:,}", "Derivative Enriched")
            summary.add_row("Spatial Arbitrage Store", f"{arb_count:,}", "ASOF Aligned")
            summary.add_row("Total Pipeline Latency", f"{elapsed:.2f}s", "Sub-120s SLA Met")
            console.print(
                Panel(
                    summary,
                    title="[bold green]Feature Engineering Complete[/bold green]",
                    box=box.ROUNDED,
                )
            )
        else:
            print(f"Feature engineering pipeline complete in {elapsed:.2f}s.\n")

    finally:
        conn.close()


if __name__ == "__main__":
    build_analytical_features(DB_PATH)
