import sys
import argparse
from pathlib import Path
import duckdb
import pandas as pd
import numpy as np
import joblib


def find_repo_root() -> Path:
    current = Path(__file__).resolve().parent
    for p in [current, current.parent, current.parent.parent]:
        if (p / "data").exists() or (p / "models").exists() or (p / "requirements.txt").exists():
            return p
    return current.parent.parent


BASE_DIR = find_repo_root()
DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"
MODEL_PATH = BASE_DIR / "models" / "xgboost_forecast.joblib"


def calculate_direct_payout_series(
    prices: pd.Series,
    tax_rate: float = 0.075,
    clamp_dead_zone: bool = True,
    is_pro: bool = False
) -> pd.Series:
    p = prices.copy().astype(float)
    if clamp_dead_zone:
        p = np.where((p >= 2.50) & (p <= 2.67), 2.49, p)
    sub_tier_fee = np.round(p * 0.50, 2)
    sub_tier_payout = p - sub_tier_fee
    commission = np.minimum(p * 0.0895, 75.00)
    pro_fee = np.minimum(p * 0.025, 75.00) if is_pro else 0.0
    gross_total = p * (1.0 + tax_rate)
    processing = gross_total * 0.025
    standard_fee = np.round(1.12 + commission + pro_fee + processing, 2)
    standard_payout = p - standard_fee
    payout = np.where(
        p < 0.40,
        0.0,
        np.where(p < 2.50, sub_tier_payout, standard_payout)
    )
    return np.maximum(0.0, payout)


def calculate_condition_risk_haircut(
    direct_price: pd.Series,
    acq_cost: pd.Series,
    downgrade_rate: float = 0.035,
    reject_rate: float = 0.005,
    salvage_factor: float = 0.75
) -> pd.Series:
    safe_direct = np.maximum(0.40, direct_price)
    downgrade_penalty = (safe_direct - (salvage_factor * acq_cost)) / safe_direct
    reject_penalty = safe_direct / safe_direct
    kappa_risk = 1.0 - (downgrade_rate * np.maximum(0.0, downgrade_penalty) + reject_rate * reject_penalty)
    return np.clip(kappa_risk, 0.80, 1.00)


def scan_market(
    tau: float = None,
    hurdle_pct: float = 10.0,
    top_n: int = 10,
    target_date: str = None,
    sort_by: str = "exp_roi",
    is_pro: bool = False,
    db_path: Path = DB_PATH,
    model_path: Path = MODEL_PATH
):
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}.", file=sys.stderr)
        sys.exit(1)
    if not model_path.exists():
        print(f"Error: Model artifact not found at {model_path}.", file=sys.stderr)
        sys.exit(1)

    artifact = joblib.load(model_path)
    classifier = artifact["classifier"]
    regressor = artifact["regressor"]
    feature_cols = artifact["feature_cols"]
    metrics = artifact.get("metrics", {})
    if tau is None:
        tau = metrics.get("prob_threshold", 0.90)

    conn = duckdb.connect(str(db_path), read_only=True, config={
        'max_memory': '1GB',
        'threads': '2'
    })
    date_filter_sql = "f.price_date = CAST(? AS DATE)" if target_date else "f.price_date = (SELECT MAX(price_date) FROM fact_card_features)"
    params = [target_date] if target_date else []
    query = f"""
        SELECT
            f.uuid, f.finish, f.price_date, f.current_price, f.sma_ratio,
            f.volatility_14d, f.daily_return_pct, f.velocity_7d_pct,
            f.bid_ask_spread_pct, f.spread_velocity_7d, f.vendor_delta_7d,
            f.is_foil, f.is_reserved, f.mana_value, f.popularity_score,
            f.is_land, f.is_creature, f.asset_age_years, f.rarity_score,
            COALESCE(d.name, f.uuid) AS name,
            COALESCE(d.set_code, 'OTC') AS set_code,
            d.collector_number
        FROM fact_card_features f
        LEFT JOIN dim_cards d ON f.uuid = d.uuid
        WHERE {date_filter_sql} AND f.current_price >= 0.40
        ORDER BY f.current_price DESC
    """
    df = conn.execute(query, params).fetchdf()
    conn.close()

    if len(df) == 0:
        print("No liquid records found.")
        return

    now_date = str(df["price_date"].iloc[0])
    total_evaluated = len(df)

    X = df[feature_cols].fillna(0.0)
    df["move_prob"] = classifier.predict_proba(X)[:, 1]
    df["ml_gain_pct"] = regressor.predict(X)

    stage1_mask = df["move_prob"] >= tau
    stage1_count = int(stage1_mask.sum())

    inbound_postage = np.where(df["current_price"] < 5.00, 0.99, 0.15)
    hub_freight = 0.012
    df["basis"] = (df["current_price"] * 1.075) + inbound_postage + hub_freight
    df["exp_exit"] = np.maximum(0.01, df["current_price"] * (1.0 + (df["ml_gain_pct"] / 100.0)))

    payout_win_raw = calculate_direct_payout_series(df["exp_exit"], clamp_dead_zone=True, is_pro=is_pro)
    kappa_win = calculate_condition_risk_haircut(df["exp_exit"], df["basis"])
    df["payout_win"] = payout_win_raw * kappa_win
    df["profit_win"] = df["payout_win"] - df["basis"]
    df["roi_win_pct"] = (df["profit_win"] / df["basis"]) * 100.0

    payout_fail_raw = calculate_direct_payout_series(df["current_price"], clamp_dead_zone=True, is_pro=is_pro)
    kappa_fail = calculate_condition_risk_haircut(df["current_price"], df["basis"])
    df["payout_fail"] = payout_fail_raw * kappa_fail
    df["profit_fail"] = df["payout_fail"] - df["basis"]
    df["loss_fail_pct"] = (df["profit_fail"] / df["basis"]) * 100.0

    p = df["move_prob"]
    df["exp_net_profit"] = (p * df["profit_win"]) + ((1.0 - p) * df["profit_fail"])
    df["exp_net_roi_pct"] = (df["exp_net_profit"] / df["basis"]) * 100.0

    b = np.maximum(0.001, df["roi_win_pct"] / 100.0)
    a = np.maximum(0.001, np.abs(df["loss_fail_pct"]) / 100.0)
    df["kelly_fraction"] = np.clip((p * b - (1.0 - p) * a) / (a * b), 0.0, 1.0)

    stage2_df = df[
        (stage1_mask) &
        (df["roi_win_pct"] >= hurdle_pct) &
        (df["ml_gain_pct"] > 0.0)
    ].copy()

    sort_columns = {
        "exp_roi": ("exp_net_roi_pct", False),
        "kelly": ("kelly_fraction", False),
        "dollars": ("exp_net_profit", False),
        "win_roi": ("roi_win_pct", False),
    }
    col, asc = sort_columns.get(sort_by, ("exp_net_roi_pct", False))
    stage2_df = stage2_df.sort_values(by=col, ascending=asc)
    stage2_count = len(stage2_df)

    print("=" * 60)
    print(f" SCANNING MARKET AT 'NOW' ({now_date})")
    print(f" Total Liquid Cards Evaluated : {total_evaluated:,}")
    print(f" Confidence Threshold (tau)   : {tau:.2f}")
    print(f" Target Net ROI Hurdle        : >= {hurdle_pct:.1f}%")
    print(f" Active Ranking Model         : {sort_by.upper()}")
    print("=" * 60)
    print(f"\n[Stage 1] Breakout Candidates (Prob >= {tau:.2f}): {stage1_count:,} cards")
    print(f"[Stage 2] Cleared Net ROI Hurdle (>= {hurdle_pct:.1f}%): {stage2_count:,} cards\n")

    if stage2_count == 0:
        print("No assets currently cleared the target hurdle.")
        return

    print(f"TOP ASSETS RANKED BY {sort_by.upper()}:")
    for _, r in stage2_df.head(top_n).iterrows():
        num_str = f" #{r['collector_number']}" if r['collector_number'] else ""
        print(f"  + {r['name']} ({r['set_code']}{num_str}) [{r['finish'].upper()}]")
        print(f"    Basis: ${r['basis']:.2f} | Exp. Exit: ${r['exp_exit']:.2f} | Net Payout: ${r['payout_win']:.2f}")
        print(f"    ML Gain: {r['ml_gain_pct']:+.1f}% (Prob: {r['move_prob']*100:.1f}%) | Win ROI: {r['roi_win_pct']:+.1f}%")
        print(f"    E[Net ROI]: {r['exp_net_roi_pct']:+.1f}% | E[Net $]: {r['exp_net_profit']:+.2f} | Kelly: {r['kelly_fraction']:.2f}")
        print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tau", "-t", type=float, default=0.90)
    parser.add_argument("--hurdle", type=float, default=10.0)
    parser.add_argument("--top", "-n", type=int, default=10)
    parser.add_argument("--sort", "-s", choices=["exp_roi", "kelly", "dollars", "win_roi"], default="exp_roi",
                        help="Ranking metric: exp_roi (default), kelly, dollars, win_roi")
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--pro", action="store_true")
    args = parser.parse_args()

    scan_market(
        tau=args.tau,
        hurdle_pct=args.hurdle,
        top_n=args.top,
        sort_by=args.sort,
        target_date=args.date,
        is_pro=args.pro
    )


if __name__ == "__main__":
    main()