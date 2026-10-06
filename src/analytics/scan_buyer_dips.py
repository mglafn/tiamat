"""
src/analytics/scan_buyer_dips.py
---------------------------------
Generalist Buyer & Deckbuilder Dip Scanner.
Analyzes acquisition value, moving-average discounts, floor stabilization,
and pre-spike breakout warnings for players with zero intention of reselling.
"""

import sys
import argparse
from pathlib import Path
import duckdb
import pandas as pd
import numpy as np
import joblib

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"
MODEL_PATH = BASE_DIR / "models" / "xgboost_forecast.joblib"

# --- Serialization shims for XGBoost unpickling ---
def smooth_asymmetric_huber_objective(y_true, y_pred):
    e = y_pred - y_true
    alpha, gamma, delta, k = 0.20, 5.0, 1.0, 10.0
    sig = 1.0 / (1.0 + np.exp(-k * e))
    dsig = k * sig * (1.0 - sig)
    ddsig = k * k * sig * (1.0 - sig) * (1.0 - 2.0 * sig)
    scale_factor = 1.0 - 2.0 * alpha + gamma
    w = alpha + scale_factor * sig
    dw = scale_factor * dsig
    ddw = scale_factor * ddsig
    u = e / delta
    sqrt_term = np.sqrt(1.0 + u**2)
    l_huber = 2.0 * (delta**2) * (sqrt_term - 1.0)
    dl_huber = 2.0 * e / sqrt_term
    ddl_huber = 2.0 / (sqrt_term**3)
    grad = dw * l_huber + w * dl_huber
    hess = ddw * l_huber + 2.0 * dw * dl_huber + w * ddl_huber
    return grad, np.maximum(hess, 1e-6)

class ConformalizedLowerBoundGenerator:
    def __init__(self, alpha: float = 0.10):
        self.alpha = alpha
        self.q_hat_conformal = None
    def predict_lpb(self, X_test):
        return np.zeros(len(X_test))

def compute_buyer_landed_cost(price: pd.Series, tax_rate: float = 0.075) -> pd.Series:
    """Acquisition price + sales tax + tiered buyer postage."""
    inbound_postage = np.where(price < 5.00, 0.99, 0.15)
    return (price * (1.0 + tax_rate)) + inbound_postage

def scan_buyer_dips(
    min_discount_pct: float = 8.0,
    max_edhrec_rank: int = 1500,
    min_price: float = 1.50,
    tax_rate: float = 0.075,
    top_n: int = 8,
    reserved_only: bool = False,
    db_path: Path = DB_PATH,
    model_path: Path = MODEL_PATH
):
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}. Please run ETL first.", file=sys.stderr)
        return

    # 1. Connect to DuckDB & pull feature store snapshot
    conn = duckdb.connect(str(db_path), read_only=True)
    reserved_clause = "AND d.is_reserved = true" if reserved_only else ""
    rank_clause = f"AND (d.edhrec_rank IS NOT NULL AND d.edhrec_rank <= {max_edhrec_rank})" if max_edhrec_rank > 0 else ""

    query = f"""
        WITH latest_snapshot AS (
            SELECT
                f.uuid, f.finish, f.price_date, f.current_price,
                f.sma_7, f.sma_30, f.daily_return_pct, f.velocity_7d_pct,
                f.price_decay_velocity_3d, f.volatility_14d, f.amihud_illiquidity_30d,
                f.is_foil, f.is_reserved, f.mana_value, f.popularity_score,
                f.is_land, f.is_creature, f.asset_age_years, f.rarity_score,
                f.sma_ratio, f.bid_ask_spread_pct, f.spread_velocity_7d, f.vendor_delta_7d,
                COALESCE(d.name, f.uuid) AS name,
                COALESCE(d.set_code, 'OTC') AS set_code,
                d.collector_number,
                d.edhrec_rank,
                d.rarity
            FROM fact_card_features f
            LEFT JOIN dim_cards d ON f.uuid = d.uuid
            WHERE f.current_price >= {min_price}
              {reserved_clause}
              {rank_clause}
            QUALIFY ROW_NUMBER() OVER(PARTITION BY f.uuid, f.finish ORDER BY f.price_date DESC) = 1
        )
        SELECT * FROM latest_snapshot
        WHERE sma_30 IS NOT NULL AND sma_30 > 0;
    """
    df = conn.execute(query).fetchdf()
    conn.close()

    if len(df) == 0:
        print("No cards matched the requested staple criteria.", file=sys.stderr)
        return

    # 2. Compute Buyer Value & Discount Metrics
    df['discount_sma30_pct'] = ((df['sma_30'] - df['current_price']) / df['sma_30']) * 100.0
    df['dollar_savings'] = df['sma_30'] - df['current_price']
    
    # Statistical Z-score against volatility
    dollar_vol = np.maximum(0.05, df['current_price'] * (df['volatility_14d'] / 100.0))
    df['z_score'] = (df['current_price'] - df['sma_30']) / dollar_vol
    df['buyer_landed_cost'] = compute_buyer_landed_cost(df['current_price'], tax_rate=tax_rate)

    # 3. Model Inference (Pre-Spike Alerts)
    df['move_prob'] = 0.0
    df['pred_spike_pct'] = 0.0
    prob_threshold = 0.85

    if model_path.exists():
        try:
            artifact = joblib.load(model_path)
            classifier = artifact.get("classifier")
            regressor = artifact.get("regressor")
            feature_cols = artifact.get("feature_cols", [])
            prob_threshold = artifact.get("metrics", {}).get("prob_threshold", 0.85)

            if classifier and all(c in df.columns for c in feature_cols):
                X = df[feature_cols].fillna(0.0)
                df['move_prob'] = classifier.predict_proba(X)[:, 1]
                if regressor:
                    df['pred_spike_pct'] = regressor.predict(X)
        except Exception:
            pass  # Fall back gracefully to pure rule-based dip detection

    # 4. Classify Market States
    # State A: Local Floor Confirmed (Decent discount + bleed flattened out)
    floor_mask = (
        (df['discount_sma30_pct'] >= min_discount_pct) &
        (df['price_decay_velocity_3d'] >= -0.25) &  # Decay velocity has stabilized
        (df['z_score'] <= -1.0)
    )

    # State B: Urgent Pre-Spike Alert (ML breakout probability >= tau)
    breakout_mask = (
        (df['move_prob'] >= prob_threshold) &
        (df['pred_spike_pct'] >= 10.0)
    )

    # State C: Falling Knife (Large drop, but decay is still accelerating downwards)
    knife_mask = (
        (df['discount_sma30_pct'] >= 12.0) &
        (df['price_decay_velocity_3d'] < -0.50) &
        (~breakout_mask)
    )

    floor_df = df[floor_mask].sort_values(by="discount_sma30_pct", ascending=False).head(top_n)
    breakout_df = df[breakout_mask].sort_values(by="move_prob", ascending=False).head(top_n)
    knife_df = df[knife_mask].sort_values(by="price_decay_velocity_3d", ascending=True).head(top_n)

    # 5. Render Output
    render_buyer_report(df, floor_df, breakout_df, knife_df, min_discount_pct, prob_threshold, top_n)

def render_buyer_report(total_df, floor_df, breakout_df, knife_df, min_discount, tau, top_n):
    if not HAS_RICH:
        print(f"\n--- TIAMAT BUYER RADAR (Universe: {len(total_df):,} staples) ---")
        print(f"Confirmed Floors: {len(floor_df)} | Pre-Spike Breakouts: {len(breakout_df)} | Falling Knives: {len(knife_df)}")
        return

    # Header Panel
    header = Table.grid(expand=True)
    header.add_column(justify="left", ratio=3)
    header.add_column(justify="right", ratio=2)
    
    title = Text()
    title.append("TIAMAT QUANT TERMINAL", style="bold cyan")
    title.append(" │ ", style="dim white")
    title.append("Staple Floor & Dip Accumulator", style="bold green")
    title.append("\nDeckbuilder Acquisition Radar • No Resale Friction • Mean-Reversion Timing", style="dim italic")

    meta = Text()
    meta.append(f"Evaluated Staples: {len(total_df):,} SKUs\n", style="dim white")
    meta.append("Acquisition Drag: [bold green]0% Seller Fee (Direct Buy Mode)[/bold green]")
    header.add_row(title, meta)
    console.print(Panel(header, box=box.ROUNDED, border_style="green", padding=(0, 1)))
    console.print()

    # Section 1: Confirmed Local Floors
    if len(floor_df) > 0:
        table_floor = Table(
            title=f"[bold green]1. CONFIRMED LOCAL FLOORS (Bleed Stopped • Ready to Buy for Decks)[/bold green]",
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold green",
            expand=True
        )
        table_floor.add_column("Card Name", style="bold white", max_width=24, overflow="ellipsis")
        table_floor.add_column("Set", justify="center", style="cyan")
        table_floor.add_column("Finish", justify="center", style="yellow")
        table_floor.add_column("EDH Rank", justify="center", style="dim")
        table_floor.add_column("Current Ask", justify="right")
        table_floor.add_column("Landed Cost", justify="right", style="dim")
        table_floor.add_column("30D Baseline", justify="right", style="cyan")
        table_floor.add_column("Dip Discount", justify="right", style="bold green")
        table_floor.add_column("Dollar Savings", justify="right", style="bold green")
        table_floor.add_column("3D Velocity", justify="right", style="dim")

        for _, r in floor_df.iterrows():
            table_floor.add_row(
                r["name"],
                r["set_code"],
                r["finish"].upper(),
                f"#{int(r['edhrec_rank']):,}" if pd.notna(r['edhrec_rank']) else "—",
                f"${r['current_price']:.2f}",
                f"${r['buyer_landed_cost']:.2f}",
                f"${r['sma_30']:.2f}",
                f"-{r['discount_sma30_pct']:.1f}%",
                f"+${r['dollar_savings']:.2f}",
                f"{r['price_decay_velocity_3d']:+.2f}%/d"
            )
        console.print(table_floor)
        console.print()
    else:
        console.print(f"[dim yellow]ℹ No active staples have stabilized at >= {min_discount:.1f}% discount today.[/dim yellow]\n")

    # Section 2: Pre-Spike Breakout Alerts
    if len(breakout_df) > 0:
        table_breakout = Table(
            title=f"[bold yellow]2. PRE-SPIKE BREAKOUT ALERTS (Buy Immediately • High Probability of Markup)[/bold yellow]",
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold yellow",
            expand=True
        )
        table_breakout.add_column("Card Name", style="bold white", max_width=24, overflow="ellipsis")
        table_breakout.add_column("Set", justify="center", style="cyan")
        table_breakout.add_column("Finish", justify="center", style="yellow")
        table_breakout.add_column("Current Price", justify="right")
        table_breakout.add_column("Breakout Prob (P)", justify="right", style="bold yellow")
        table_breakout.add_column("Predicted Spike", justify="right", style="bold green")
        table_breakout.add_column("Projected 7D Price", justify="right", style="cyan")
        table_breakout.add_column("Action Directive", style="bold white")

        for _, r in breakout_df.iterrows():
            proj_price = r['current_price'] * (1.0 + r['pred_spike_pct'] / 100.0)
            table_breakout.add_row(
                r["name"],
                r["set_code"],
                r["finish"].upper(),
                f"${r['current_price']:.2f}",
                f"{r['move_prob']:.1%}",
                f"+{r['pred_spike_pct']:.1f}%",
                f"${proj_price:.2f}",
                "[bold red]BUY BEFORE SPIKE[/bold red]"
            )
        console.print(table_breakout)
        console.print()
    else:
        console.print("[dim green]✔ No imminent buyout spikes detected across tracked staple universe.[/dim green]\n")

    # Section 3: Falling Knife Warning
    if len(knife_df) > 0:
        table_knife = Table(
            title=f"[bold magenta]3. FALLING KNIFE VETO (Patience Shield • Bleed Still Accelerating)[/bold magenta]",
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold magenta",
            expand=True
        )
        table_knife.add_column("Card Name", style="bold white", max_width=24, overflow="ellipsis")
        table_knife.add_column("Set", justify="center", style="cyan")
        table_knife.add_column("Finish", justify="center", style="yellow")
        table_knife.add_column("Current Ask", justify="right")
        table_knife.add_column("Discount vs 30D", justify="right", style="magenta")
        table_knife.add_column("Decay Velocity", justify="right", style="bold red")
        table_knife.add_column("Advisory Recommendation", style="italic dim")

        for _, r in knife_df.iterrows():
            table_knife.add_row(
                r["name"],
                r["set_code"],
                r["finish"].upper(),
                f"${r['current_price']:.2f}",
                f"-{r['discount_sma30_pct']:.1f}%",
                f"{r['price_decay_velocity_3d']:.2f}%/d",
                "DO NOT BUY YET — Bleed active"
            )
        console.print(table_knife)
        console.print()

def main():
    parser = argparse.ArgumentParser(
        description="Tiamat Quant Terminal - Generalist Buyer & Deckbuilder Dip Scanner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--min-discount", type=float, default=8.0, help="Minimum %% discount below 30D SMA")
    parser.add_argument("--max-rank", type=int, default=1500, help="Max EDHREC rank filter (0 for all cards)")
    parser.add_argument("--min-price", type=float, default=2.00, help="Minimum retail floor price to evaluate")
    parser.add_argument("--tax", type=float, default=7.5, help="Estimated local sales tax %%")
    parser.add_argument("--top", "-n", type=int, default=8, help="Number of records to display in each section")
    parser.add_argument("--reserved-only", action="store_true", help="Scan only Reserved List assets")
    args = parser.parse_args()

    scan_buyer_dips(
        min_discount_pct=args.min_discount,
        max_edhrec_rank=args.max_rank,
        min_price=args.min_price,
        tax_rate=args.tax / 100.0,
        top_n=args.top,
        reserved_only=args.reserved_only
    )

if __name__ == "__main__":
    main()