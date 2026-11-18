"""
src/analytics/scan_buyer_dips.py
---------------------------------
Generalist Buyer & Deckbuilder Dip Scanner.
Analyzes acquisition value, moving-average discounts, floor stabilization,
and pre-spike breakout warnings for players with zero intention of reselling.
"""

import argparse
from pathlib import Path
import sys
import duckdb

from src.analytics.inference import predict_buyer_breakout, try_load_forecast_bundle
from src.cli.reports import render_buyer_report
from src.config import DB_PATH, FEE_CONFIG, MODEL_CONFIG, MODEL_PATH
from src.pricing.fees import landed_basis_series


def scan_buyer_dips(
    min_discount_pct: float = 8.0,
    max_edhrec_rank: int = 1500,
    min_price: float = 1.50,
    tax_rate: float = FEE_CONFIG["DEFAULT_TAX_RATE"],
    top_n: int = 8,
    reserved_only: bool = False,
    db_path: Path = DB_PATH,
    model_path: Path = MODEL_PATH,
):
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}. Please run ETL first.", file=sys.stderr)
        return

    # 1. Connect to DuckDB & pull feature store snapshot
    reserved_clause = "AND d.is_reserved = true" if reserved_only else ""
    params: list[object] = [float(min_price)]
    rank_clause = ""
    if max_edhrec_rank > 0:
        rank_clause = "AND (d.edhrec_rank IS NOT NULL AND d.edhrec_rank <= ?)"
        params.append(int(max_edhrec_rank))

    query = f"""
        WITH latest_snapshot AS (
            SELECT
                f.uuid, f.finish, f.price_date, f.current_price,
                f.sma_7, f.sma_30, f.daily_return_pct, f.velocity_7d_pct,
                f.price_decay_velocity_3d, f.volatility_14d, f.amihud_illiquidity_30d,
                f.z_downside_3d, f.velocity_3d, f.accel_3d, f.exhaustion_ratio,
                f.microstructure_regime,
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
            WHERE f.current_price >= ?
              {reserved_clause}
              {rank_clause}
            QUALIFY ROW_NUMBER() OVER(PARTITION BY f.uuid, f.finish ORDER BY f.price_date DESC) = 1
        )
        SELECT * FROM latest_snapshot
        WHERE sma_30 IS NOT NULL AND sma_30 > 0;
    """
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        df = conn.execute(query, params).fetchdf()
    finally:
        conn.close()

    if len(df) == 0:
        print("No cards matched the requested staple criteria.", file=sys.stderr)
        return

    # 2. Compute Buyer Value & Discount Metrics
    df["discount_sma30_pct"] = ((df["sma_30"] - df["current_price"]) / df["sma_30"]) * 100.0
    df["dollar_savings"] = df["sma_30"] - df["current_price"]
    df["buyer_landed_cost"] = landed_basis_series(
        df["current_price"], tax_rate=tax_rate, channel="buyer"
    )

    # 3. Model Inference (Pre-Spike Alerts)
    df["move_prob"] = 0.0
    df["pred_spike_pct"] = 0.0
    prob_threshold = 0.40

    bundle = try_load_forecast_bundle(model_path)
    if bundle is not None:
        prob_threshold = bundle.tau_buyer_radar
        if all(c in df.columns for c in bundle.feature_cols):
            X = df[list(bundle.feature_cols)].fillna(0.0)
            move_prob, pred_q90 = predict_buyer_breakout(bundle, X)
            df["move_prob"] = move_prob
            df["pred_spike_pct"] = pred_q90

    # 4. Classify Market States (aligned with verify_buyer_dips.py regimes)
    # State A: Local Floor Confirmed (Scale-Invariant Deceleration + SMA discount)
    floor_mask = (df["microstructure_regime"] == "CONFIRMED_LOCAL_BOTTOM") & (
        df["discount_sma30_pct"] >= min_discount_pct
    )

    # State B: Urgent Pre-Spike Alert (Calibrated q_0.90 breakout probability >= tau)
    breakout_mask = (df["move_prob"] >= prob_threshold) & (
        df["pred_spike_pct"] >= MODEL_CONFIG["SPIKE_THRESHOLD_PCT"]
    )

    # State C: Falling Knife (Scale-invariant downward acceleration)
    knife_mask = (df["microstructure_regime"] == "FALLING_KNIFE") & (~breakout_mask)

    floor_df = df[floor_mask].sort_values(by="discount_sma30_pct", ascending=False).head(top_n)
    breakout_df = df[breakout_mask].sort_values(by="move_prob", ascending=False).head(top_n)
    knife_df = df[knife_mask].sort_values(by="price_decay_velocity_3d", ascending=True).head(top_n)

    # 5. Render Output
    render_buyer_report(
        df, floor_df, breakout_df, knife_df, min_discount_pct, prob_threshold, top_n
    )


def main():
    parser = argparse.ArgumentParser(
        description="Tiamat Quant Terminal - Generalist Buyer & Deckbuilder Dip Scanner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--min-discount", type=float, default=8.0, help="Minimum %% discount below 30D SMA"
    )
    parser.add_argument(
        "--max-rank", type=int, default=1500, help="Max EDHREC rank filter (0 for all cards)"
    )
    parser.add_argument(
        "--min-price", type=float, default=2.00, help="Minimum retail floor price to evaluate"
    )
    parser.add_argument("--tax", type=float, default=7.5, help="Estimated local sales tax %%")
    parser.add_argument(
        "--top", "-n", type=int, default=8, help="Number of records to display in each section"
    )
    parser.add_argument(
        "--reserved-only", action="store_true", help="Scan only Reserved List assets"
    )
    args = parser.parse_args()

    scan_buyer_dips(
        min_discount_pct=args.min_discount,
        max_edhrec_rank=args.max_rank,
        min_price=args.min_price,
        tax_rate=args.tax / 100.0,
        top_n=args.top,
        reserved_only=args.reserved_only,
    )


if __name__ == "__main__":
    main()
