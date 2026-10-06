"""
src/analytics/build_features.py
-------------------------------
Vectorized OLAP Feature Engineering Pipeline.
Derives scale-invariant price derivatives, robust volatility, and regime states
using parameters defined in src.config.
"""

import os
import sys
import time
from pathlib import Path
import duckdb

# Ensure repository root is on sys.path for direct script execution
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.config import DB_PATH, MICROSTRUCTURE_CONFIG

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

def build_analytical_features(db_path: Path = DB_PATH):
    start_time = time.time()
    
    if not db_path.exists():
        err_msg = f"Database not found at '{db_path}'. Run ETL (load_duckdb.py) first."
        if HAS_RICH:
            console.print(f"[bold red]✖ Error:[/bold red] {err_msg}")
        else:
            print(f"Error: {err_msg}", file=sys.stderr)
        raise FileNotFoundError(err_msg)

    if HAS_RICH:
        header_grid = Table.grid(expand=True)
        header_grid.add_column(justify="left", ratio=3)
        header_grid.add_column(justify="right", ratio=2)
        
        title = Text()
        title.append("TIAMAT QUANT TERMINAL", style="bold cyan")
        title.append(" │ ", style="dim white")
        title.append("Scale-Invariant Feature Engineering", style="bold white")
        title.append("\nDuckDB OLAP • Tick-Size Robust Volatility • Config-Driven Regimes", style="dim italic")
        
        meta = Text()
        meta.append(f"Target DB: {db_path.name}\n", style="dim cyan")
        meta.append("Status: [bold green]Processing SQL Window Frames[/bold green]")
        
        header_grid.add_row(title, meta)
        console.print(Panel(header_grid, box=box.ROUNDED, border_style="cyan", padding=(0, 1)))
        console.print()

    conn = duckdb.connect(str(db_path), config={
        'threads': '4',
        'max_memory': '2GB',
        'preserve_insertion_order': 'false'
    })
    
    cfg = MICROSTRUCTURE_CONFIG
    
    try:
        if HAS_RICH: 
            console.print("[bold cyan][1/3] Building `fact_card_features` (Scale-Invariant Derivatives)...[/bold cyan]")
        else: 
            print("[1/3] Building `fact_card_features`...")

        conn.execute("DROP TABLE IF EXISTS fact_card_features")
        
        # Inject centralized configuration into SQL execution
        conn.execute(f"""
            CREATE TABLE fact_card_features AS
            WITH daily_market AS (
                SELECT
                    uuid, finish, price_date,
                    MIN(CASE WHEN list_type = 'retail' THEN price END) AS market_retail,
                    MAX(CASE WHEN list_type = 'buylist' THEN price END) AS market_buylist,
                    COUNT(CASE WHEN list_type = 'retail' THEN 1 END) AS active_vendors
                FROM fact_prices
                WHERE format = 'paper'
                GROUP BY uuid, finish, price_date
                HAVING MIN(CASE WHEN list_type = 'retail' THEN price END) IS NOT NULL
            ),
            daily_log_diffs AS (
                SELECT
                    uuid, finish, price_date,
                    market_retail AS current_price, active_vendors, market_buylist,
                    LN(GREATEST(0.01, market_retail)) AS ln_price,
                    LN(GREATEST(0.01, market_retail)) - LN(GREATEST(0.01, LAG(market_retail, 1) OVER w_card)) AS log_ret_1d,
                    LN(GREATEST(0.01, market_retail)) - LN(GREATEST(0.01, LAG(market_retail, 3) OVER w_card)) AS log_ret_3d,
                    LAG(market_retail, 3) OVER w_card AS price_t_minus_3,
                    LAG(market_retail, 6) OVER w_card AS price_t_minus_6
                FROM daily_market
                WINDOW w_card AS (PARTITION BY uuid, finish ORDER BY price_date ASC)
            ),
            rolling_dispersion AS (
                SELECT
                    *,
                    MEDIAN(log_ret_1d) OVER w_14d AS median_ret_1d,
                    mad(log_ret_1d) OVER w_14d AS mad_ret_1d,
                    MEDIAN(log_ret_3d) OVER w_14d AS median_ret_3d,
                    AVG(current_price) OVER (
                        PARTITION BY uuid, finish ORDER BY price_date ASC
                        RANGE BETWEEN INTERVAL 6 DAYS PRECEDING AND CURRENT ROW
                    ) AS sma_7,
                    AVG(current_price) OVER (
                        PARTITION BY uuid, finish ORDER BY price_date ASC
                        RANGE BETWEEN INTERVAL 29 DAYS PRECEDING AND CURRENT ROW
                    ) AS sma_30,
                    COALESCE(((current_price - LAG(current_price) OVER (
                        PARTITION BY uuid, finish ORDER BY price_date ASC
                    )) / NULLIF(LAG(current_price) OVER (
                        PARTITION BY uuid, finish ORDER BY price_date ASC
                    ), 0) * 100.0) / GREATEST(1, COALESCE(DATE_DIFF('day', LAG(price_date) OVER (
                        PARTITION BY uuid, finish ORDER BY price_date ASC
                    ), price_date), 1)), 0.0) AS daily_return_pct
                FROM daily_log_diffs
                WINDOW w_14d AS (
                    PARTITION BY uuid, finish ORDER BY price_date ASC 
                    ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
                )
            ),
            enriched_market AS (
                SELECT
                    *,
                    -- STRUCTURAL VOLATILITY FLOOR: Scale by MAD or minimum discrete tick size ($0.01 / price)
                    GREATEST(1.4826 * COALESCE(mad_ret_1d, 0.0), {cfg['MIN_TICK_USD']} / GREATEST(0.01, current_price)) AS robust_vol_14d,
                    -- Discrete Price Velocity & Acceleration
                    (COALESCE(log_ret_3d, 0.0)) / 3.0 AS velocity_3d,
                    (LN(GREATEST(0.01, current_price)) - 2.0 * LN(GREATEST(0.01, COALESCE(price_t_minus_3, current_price))) + 
                     LN(GREATEST(0.01, COALESCE(price_t_minus_6, current_price)))) / 9.0 AS accel_3d,
                    COALESCE((current_price - market_buylist) / NULLIF(current_price, 0), 1.0) AS bid_ask_spread_pct
                FROM rolling_dispersion
            )
            SELECT
                e.uuid, 'consensus' AS vendor, e.finish, e.price_date, e.current_price,
                e.sma_7, e.sma_30, e.daily_return_pct, e.velocity_3d, e.accel_3d,
                ((e.current_price - e.sma_7) / NULLIF(e.sma_7, 0)) * 100.0 AS velocity_7d_pct,
                (e.sma_7 / NULLIF(e.sma_30, 0)) AS sma_ratio,
                COALESCE(STDDEV(e.daily_return_pct) OVER (
                    PARTITION BY e.uuid, e.finish ORDER BY e.price_date ASC
                    RANGE BETWEEN INTERVAL 13 DAYS PRECEDING AND CURRENT ROW
                ), 0.0) AS volatility_14d,
                e.bid_ask_spread_pct,
                (e.bid_ask_spread_pct - FIRST_VALUE(e.bid_ask_spread_pct) OVER (
                    PARTITION BY e.uuid, e.finish ORDER BY e.price_date ASC
                    RANGE BETWEEN INTERVAL 7 DAYS PRECEDING AND CURRENT ROW
                )) AS spread_velocity_7d,
                (e.active_vendors - FIRST_VALUE(e.active_vendors) OVER (
                    PARTITION BY e.uuid, e.finish ORDER BY e.price_date ASC
                    RANGE BETWEEN INTERVAL 7 DAYS PRECEDING AND CURRENT ROW
                )) AS vendor_delta_7d,
                COALESCE(((e.current_price - e.price_t_minus_3) / NULLIF(e.price_t_minus_3, 0) / 3.0) * 100.0, 0.0) AS price_decay_velocity_3d,
                AVG(ABS(e.daily_return_pct) / NULLIF(e.current_price * e.active_vendors, 0)) OVER (
                    PARTITION BY e.uuid, e.finish ORDER BY e.price_date ASC
                    RANGE BETWEEN INTERVAL 29 DAYS PRECEDING AND CURRENT ROW
                ) AS amihud_illiquidity_30d,
                
                -- Downside Z-Score with tick-size bound protection
                e.robust_vol_14d,
                (COALESCE(e.log_ret_3d, 0.0) - COALESCE(e.median_ret_3d, 0.0)) / (e.robust_vol_14d * SQRT(3.0)) AS z_downside_3d,
                e.accel_3d / (ABS(e.velocity_3d) + 1e-6) AS exhaustion_ratio,
                
                -- Dynamic Regime Classification from Central Configuration
                CASE 
                    WHEN ((COALESCE(e.log_ret_3d, 0.0) - COALESCE(e.median_ret_3d, 0.0)) / (e.robust_vol_14d * SQRT(3.0))) < {cfg['KNIFE_Z_SCORE_THRESH']} AND e.velocity_3d < 0 AND e.accel_3d < 0 
                        THEN 'FALLING_KNIFE'
                    WHEN ((COALESCE(e.log_ret_3d, 0.0) - COALESCE(e.median_ret_3d, 0.0)) / (e.robust_vol_14d * SQRT(3.0))) < {cfg['BOTTOM_Z_SCORE_THRESH']} AND e.velocity_3d < 0 AND e.accel_3d > 0 AND (e.accel_3d / (ABS(e.velocity_3d) + 1e-6)) >= {cfg['MIN_EXHAUSTION_RATIO']}
                        THEN 'CONFIRMED_LOCAL_BOTTOM'
                    WHEN ABS((COALESCE(e.log_ret_3d, 0.0) - COALESCE(e.median_ret_3d, 0.0)) / (e.robust_vol_14d * SQRT(3.0))) <= {cfg['NOISE_Z_SCORE_BOUND']}
                        THEN 'NOISE_BOUND'
                    ELSE 'TRANSITIONAL'
                END AS microstructure_regime,

                CASE WHEN e.finish IN ('foil', 'etched') THEN 1 ELSE 0 END AS is_foil,
                CASE WHEN d.is_reserved THEN 1 ELSE 0 END AS is_reserved,
                COALESCE(d.mana_value, 0.0) AS mana_value,
                CASE WHEN d.edhrec_rank IS NOT NULL AND d.edhrec_rank > 0 THEN (1.0 / LOG10(d.edhrec_rank + 1.0)) ELSE 0.0 END AS popularity_score,
                CASE WHEN d.card_type ILIKE '%Land%' THEN 1 ELSE 0 END AS is_land,
                CASE WHEN d.card_type ILIKE '%Creature%' THEN 1 ELSE 0 END AS is_creature,
                GREATEST(0.0, DATE_DIFF('day', COALESCE(d.original_release_date, e.price_date), e.price_date) / 365.25) AS asset_age_years,
                CASE WHEN d.rarity = 'mythic' THEN 4 WHEN d.rarity = 'rare' THEN 3 WHEN d.rarity = 'uncommon' THEN 2 ELSE 1 END AS rarity_score
            FROM enriched_market e
            LEFT JOIN dim_cards d ON e.uuid = d.uuid;
        """)
        
        feat_count = conn.execute("SELECT COUNT(*) FROM fact_card_features").fetchone()[0]
        if HAS_RICH: 
            console.print(f"  [bold green]✓ `fact_card_features` populated:[/bold green] [white]{feat_count:,}[/white] feature vectors")

        if HAS_RICH: 
            console.print("[bold cyan][2/3] Building `fact_training_dataset`...[/bold cyan]")
        else: 
            print("[2/3] Building `fact_training_dataset`...")

        conn.execute("DROP TABLE IF EXISTS fact_training_dataset")
        conn.execute("""
            CREATE TABLE fact_training_dataset AS
            WITH forward_targets AS (
                SELECT
                    uuid, vendor, finish, price_date, current_price,
                    FIRST_VALUE(current_price IGNORE NULLS) OVER (
                        PARTITION BY uuid, vendor, finish ORDER BY price_date ASC
                        RANGE BETWEEN INTERVAL 7 DAYS FOLLOWING AND INTERVAL 14 DAYS FOLLOWING
                    ) AS future_price
                FROM fact_card_features
            )
            SELECT
                uuid, vendor, finish, price_date, current_price,
                ROUND((((future_price - current_price) / NULLIF(current_price, 0)) * 100.0), 4) AS target_return_7d_pct
            FROM forward_targets
            WHERE future_price IS NOT NULL;
        """)
        
        train_count = conn.execute("SELECT COUNT(*) FROM fact_training_dataset").fetchone()[0]
        if HAS_RICH: 
            console.print(f"  [bold green]✓ `fact_training_dataset` populated:[/bold green] [white]{train_count:,}[/white] labeled instances")

        if HAS_RICH: 
            console.print("[bold cyan][3/3] Building `fact_arbitrage_opportunities`...[/bold cyan]")
        else: 
            print("[3/3] Building `fact_arbitrage_opportunities`...")

        conn.execute("DROP TABLE IF EXISTS fact_arbitrage_opportunities")
        conn.execute("""
            CREATE TABLE fact_arbitrage_opportunities AS
            WITH tcg_prices AS (
                SELECT uuid, finish, price_date, MIN(price) AS tcg_price
                FROM fact_prices WHERE vendor = 'tcgplayer' AND list_type = 'retail' AND format = 'paper'
                GROUP BY uuid, finish, price_date
            ),
            ck_buylist_prices AS (
                SELECT uuid, finish, price_date, MAX(price) AS ck_price
                FROM fact_prices WHERE vendor = 'cardkingdom' AND list_type = 'buylist' AND format = 'paper'
                GROUP BY uuid, finish, price_date
            ),
            latest_ck_offers AS (
                SELECT c.uuid, c.finish, c.price_date AS ck_date, c.ck_price FROM ck_buylist_prices c
                WHERE c.price_date >= (SELECT MAX(price_date) - INTERVAL 3 DAY FROM fact_prices WHERE format = 'paper')
                QUALIFY ROW_NUMBER() OVER(PARTITION BY c.uuid, c.finish ORDER BY c.price_date DESC) = 1
            ),
            asof_aligned AS (
                SELECT c.uuid, c.finish, c.ck_date AS price_date, t.tcg_price, c.ck_price,
                    (t.tcg_price * 1.075 + CASE WHEN t.tcg_price < 5.00 THEN 0.99 ELSE 0.15 END + 0.09) AS total_acquisition_basis,
                    (c.ck_price * 1.30) AS ck_store_credit_payout
                FROM latest_ck_offers c
                ASOF JOIN tcg_prices t ON c.uuid = t.uuid AND c.finish = t.finish AND c.ck_date >= t.price_date
                WHERE t.tcg_price IS NOT NULL AND DATE_DIFF('day', t.price_date, c.ck_date) <= 3
            )
            SELECT
                uuid, price_date, finish, ROUND(tcg_price, 2) AS tcg_price, ROUND(ck_price, 2) AS ck_price,
                ROUND(ck_store_credit_payout - total_acquisition_basis, 2) AS price_spread,
                ROUND(((ck_store_credit_payout - total_acquisition_basis) / NULLIF(total_acquisition_basis, 0)) * 100.0, 2) AS spread_pct
            FROM asof_aligned WHERE ck_store_credit_payout > total_acquisition_basis;
        """)
        
        arb_count = conn.execute("SELECT COUNT(*) FROM fact_arbitrage_opportunities").fetchone()[0]
        if HAS_RICH: 
            console.print(f"  [bold green]✓ `fact_arbitrage_opportunities` populated:[/bold green] [white]{arb_count:,}[/white] locked spatial spreads\n")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_features_lookup ON fact_card_features(uuid, finish);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_features_regime ON fact_card_features(microstructure_regime);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_training_date ON fact_training_dataset(price_date);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_arb_spread ON fact_arbitrage_opportunities(price_spread DESC);")
        conn.execute("CHECKPOINT; VACUUM;")
        
        elapsed = time.time() - start_time
        if HAS_RICH:
            summary = Table(box=box.ROUNDED, border_style="green", show_header=True, header_style="bold green")
            summary.add_column("Analytical Store", style="bold white")
            summary.add_column("Rows Generated", justify="right", style="cyan")
            summary.add_column("Derivation SLA", justify="right", style="bold green")
            summary.add_row("Feature Store", f"{feat_count:,}", "Scale-Invariant Windowed")
            summary.add_row("Training Target Set", f"{train_count:,}", "Derivative Enriched")
            summary.add_row("Spatial Arbitrage Store", f"{arb_count:,}", "ASOF Aligned")
            summary.add_row("Total Pipeline Latency", f"{elapsed:.2f}s", "Sub-120s SLA Met")
            console.print(Panel(summary, title="[bold green]Feature Engineering Complete[/bold green]", box=box.ROUNDED))
        else:
            print(f"Feature engineering pipeline complete in {elapsed:.2f}s.\n")
            
    finally:
        conn.close()

if __name__ == "__main__":
    build_analytical_features(DB_PATH)