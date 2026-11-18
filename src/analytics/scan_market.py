import argparse
from pathlib import Path
import sys
import duckdb

from src.analytics.inference import (
    BuyerRadarProxyFlipperRule,
    evaluate_direct_flip_frame,
    load_forecast_bundle,
    predict_quantiles,
)
from src.analytics.sizing import FixedCapSizingPolicy, FlatSizingPolicy
from src.cli.reports import render_market_scan_report
from src.config import DB_PATH, FEATURE_COLS, MODEL_PATH
from src.pricing.fees import ck_credit_payout_sql, spatial_landed_basis_sql


def scan_live_market(
    min_net_roi_pct: float = 8.0,
    min_spread: float = 0.0,
    tau: float = None,
    sizing: str = "kelly",
    is_pro: bool = False,
    db_path: Path = DB_PATH,
    model_path: Path = MODEL_PATH,
    top_n_records: int = 8,
    as_dict: bool = False,
):
    if not model_path.exists() or not db_path.exists():
        err_msg = f"Missing database ({db_path}) or model artifact ({model_path})."
        if as_dict:
            raise FileNotFoundError(err_msg)
        print(f"Error: {err_msg}", file=sys.stderr)
        return

    bundle = load_forecast_bundle(model_path)
    prob_threshold = tau if tau is not None else bundle.tau_buyer_radar
    basis_sql = spatial_landed_basis_sql("f.tcg_price")
    payout_sql = ck_credit_payout_sql("f.ck_price")
    feature_select_sql = ", ".join([f"f.{col}" for col in FEATURE_COLS])

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        spatial_query = f"""
            SELECT
                f.uuid,
                COALESCE(d.name, f.uuid) AS name,
                COALESCE(d.set_code, 'OTC') AS set_code,
                f.finish,
                f.price_date,
                f.tcg_price,
                f.ck_price,
                {basis_sql} AS total_acquisition_basis,
                {payout_sql} AS ck_store_credit_payout,
                f.price_spread,
                f.spread_pct
            FROM fact_arbitrage_opportunities f
            LEFT JOIN dim_cards d ON f.uuid = d.uuid
            WHERE f.price_spread >= ?
            ORDER BY f.price_spread DESC
            LIMIT ?
        """
        spatial_df = conn.execute(spatial_query, [float(min_spread), int(top_n_records)]).fetchdf()

        features_query = f"""
            WITH latest_features AS (
                SELECT
                    f.uuid, f.finish, f.price_date, f.current_price,
                    {feature_select_sql},
                    COALESCE(d.name, f.uuid) AS name,
                    COALESCE(d.set_code, 'OTC') AS set_code
                FROM fact_card_features f
                LEFT JOIN dim_cards d ON f.uuid = d.uuid
                WHERE f.current_price >= 0.40
                QUALIFY ROW_NUMBER() OVER(
                    PARTITION BY f.uuid, f.finish ORDER BY f.price_date DESC
                ) = 1
            )
            SELECT * FROM latest_features
            ORDER BY current_price DESC
        """
        market_df = conn.execute(features_query).fetchdf()
    finally:
        conn.close()

    if len(market_df) == 0:
        return {"status": "empty", "message": "No active market records found"} if as_dict else None

    X_live = market_df[list(bundle.feature_cols)].fillna(0.0)
    preds = predict_quantiles(bundle, X_live)
    market_df["move_prob"] = preds.move_prob
    market_df["pred_magnitude"] = preds.q50
    market_df["cqr_lpb"] = preds.q10

    sizing_policy = FixedCapSizingPolicy() if sizing == "kelly" else FlatSizingPolicy()
    market_df = evaluate_direct_flip_frame(market_df, is_pro=is_pro, sizing_policy=sizing_policy)

    rule = BuyerRadarProxyFlipperRule(
        prob_threshold=prob_threshold,
        min_net_roi_pct=min_net_roi_pct,
    )
    gates = rule.evaluate_batch(market_df)
    funnel_counts = gates.funnel_counts("Total Scanned Active SKUs", include_sizing=True)

    directional_candidates = (
        market_df[gates.passed]
        .copy()
        .sort_values(by="exp_net_roi_pct", ascending=False)
        .head(top_n_records)
    )
    trap_mask = gates.stage1_spike & (~gates.passed)
    vetoed_df = (
        market_df[trap_mask]
        .copy()
        .sort_values(by="pred_magnitude", ascending=False)
        .head(top_n_records)
    )
    if len(vetoed_df) > 0:
        vetoed_df["veto_reason"] = vetoed_df.apply(rule.primary_veto_reason, axis=1)

    def sanitize_rows(df_sub):
        if len(df_sub) == 0:
            return []
        out = []
        for _, r in df_sub.iterrows():
            out.append(
                {
                    "uuid": r["uuid"],
                    "name": r["name"],
                    "set_code": r["set_code"],
                    "finish": r["finish"],
                    "current_price": round(float(r["current_price"]), 2),
                    "pred_magnitude": round(float(r.get("pred_magnitude", 0.0)), 2),
                    "cqr_lpb": round(float(r.get("cqr_lpb", 0.0)), 2),
                    "exp_net_roi_pct": round(float(r.get("exp_net_roi_pct", 0.0)), 2),
                    "exp_exit_payout": round(float(r.get("exp_exit_payout", 0.0)), 2),
                    "allocated_units": int(r.get("allocated_units", 1)),
                    "veto_reason": r.get("veto_reason", None),
                }
            )
        return out

    payload = {
        "status": "success",
        "meta": {
            "latest_date": str(market_df["price_date"].max().date()),
            "scanned_universe": len(market_df),
            "prob_threshold": prob_threshold,
            "min_net_roi_pct": min_net_roi_pct,
        },
        "funnel": funnel_counts,
        "spatial_arbitrage": spatial_df.to_dict(orient="records"),
        "directional_alpha": sanitize_rows(directional_candidates),
        "vetoed_traps": sanitize_rows(vetoed_df),
    }

    if not as_dict:
        render_market_scan_report(payload)

    return payload


def main():
    parser = argparse.ArgumentParser(
        description="Tiamat Quant Terminal - Live Market Scanner (Spatial & CQR Directional)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--hurdle", type=float, default=8.0, help="Minimum expected net ROI %% hurdle"
    )
    parser.add_argument(
        "--min-spread",
        type=float,
        default=0.0,
        help="Minimum dollar price spread for spatial buylist arb",
    )
    parser.add_argument(
        "--tau",
        type=float,
        default=None,
        help="Spike probability threshold (default: auto from model)",
    )
    parser.add_argument(
        "--sizing", choices=["flat", "kelly"], default="kelly", help="Position sizing model"
    )
    parser.add_argument(
        "--pro", action="store_true", help="Use TCGplayer Pro seller rate card (+2.5%% Pro fee)"
    )
    parser.add_argument(
        "--top", "-n", type=int, default=8, help="Number of records to display in each section"
    )
    args = parser.parse_args()

    scan_live_market(
        min_net_roi_pct=args.hurdle,
        min_spread=args.min_spread,
        tau=args.tau,
        sizing=args.sizing,
        is_pro=args.pro,
        top_n_records=args.top,
    )


if __name__ == "__main__":
    main()
