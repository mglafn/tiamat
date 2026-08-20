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
    from rich.columns import Columns
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False


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


def evaluate_dataframe_trades(df: pd.DataFrame, is_pro: bool, sizing: str) -> pd.DataFrame:
    if len(df) == 0:
        return df
    out = df.copy()
    if sizing == "kelly":
        out['allocated_units'] = np.maximum(1.0, np.round(out['kelly_fraction'] * 10.0 * 0.5))
    else:
        out['allocated_units'] = 1.0
    out['actual_future_price'] = out['current_price'] * (1.0 + out['target_return_7d_pct'] / 100.0)
    raw_realized_payout = calculate_direct_payout_series(out['actual_future_price'], clamp_dead_zone=True, is_pro=is_pro)
    realized_kappa = calculate_condition_risk_haircut(out['actual_future_price'], out['basis'])
    out['realized_exit_payout'] = raw_realized_payout * realized_kappa
    out['unit_profit'] = out['realized_exit_payout'] - out['basis']
    out['net_roi_pct'] = (out['unit_profit'] / out['basis']) * 100.0
    out['is_win'] = out['unit_profit'] > 0
    out['total_cost'] = out['basis'] * out['allocated_units']
    out['total_profit'] = out['unit_profit'] * out['allocated_units']
    return out


def run_arbitrage_backtest(
    min_net_roi_pct: float = 10.0,
    tau: float = None,
    sort_by: str = "exp_roi",
    filter_mode: str = "exp_roi",
    sizing: str = "flat",
    top_daily: int = 0,
    show_ablation: bool = True,
    is_pro: bool = False,
    db_path: Path = DB_PATH,
    model_path: Path = MODEL_PATH,
    as_dict: bool = False
):
    if not model_path.exists() or not db_path.exists():
        err_msg = f"Missing database ({db_path}) or model artifact ({model_path})."
        if as_dict:
            raise FileNotFoundError(err_msg)
        print(f"Error: {err_msg}", file=sys.stderr)
        return

    artifact = joblib.load(model_path)
    classifier = artifact["classifier"]
    regressor = artifact["regressor"]
    feature_cols = artifact["feature_cols"]
    metrics = artifact.get("metrics", {})
    prob_threshold = tau if tau is not None else metrics.get("prob_threshold", 0.90)
    persisted_split_date = metrics.get("split_date", None)

    conn = duckdb.connect(str(db_path), read_only=True, config={
        'max_memory': '1.5GB',
        'threads': '2'
    })
    query = """
        SELECT
            t.uuid, t.finish, t.price_date, t.current_price, t.target_return_7d_pct,
            t.sma_ratio, t.volatility_14d, t.daily_return_pct, t.velocity_7d_pct,
            t.bid_ask_spread_pct, t.spread_velocity_7d, t.vendor_delta_7d,
            t.is_foil, t.is_reserved, t.mana_value, t.popularity_score,
            t.is_land, t.is_creature, t.asset_age_years, t.rarity_score,
            COALESCE(d.name, t.uuid) AS name,
            COALESCE(d.set_code, 'OTC') AS set_code,
            d.collector_number
        FROM fact_training_dataset t
        LEFT JOIN dim_cards d ON t.uuid = d.uuid
        WHERE t.current_price >= 0.40
        ORDER BY t.price_date ASC
    """
    df = conn.execute(query).fetchdf()
    conn.close()

    if len(df) == 0:
        if as_dict:
            return {"status": "empty", "message": "No historical instances in dataset"}
        print("No historical instances found.", file=sys.stderr)
        return

    df['price_date'] = pd.to_datetime(df['price_date'])
    if persisted_split_date:
        test_start_date = pd.to_datetime(persisted_split_date)
    else:
        val_idx = int(len(df) * 0.85)
        test_start_date = df.loc[val_idx, 'price_date'] + pd.Timedelta(days=14)

    test_df = df[df['price_date'] >= test_start_date].copy().reset_index(drop=True)
    total_test_universe = len(test_df)
    if total_test_universe == 0:
        if as_dict:
            return {"status": "empty", "message": f"No records >= {test_start_date.date()}"}
        print(f"No records found in test window.", file=sys.stderr)
        return

    # Inference & Bayesian calculations
    X_test = test_df[feature_cols].fillna(0.0)
    test_df['move_prob'] = classifier.predict_proba(X_test)[:, 1]
    test_df['pred_magnitude'] = regressor.predict(X_test)
    test_df['pred_return_7d'] = np.where(test_df['move_prob'] >= prob_threshold, test_df['pred_magnitude'], 0.0)

    inbound_postage = np.where(test_df['current_price'] < 5.00, 0.99, 0.15)
    hub_freight = 0.012
    test_df['basis'] = (test_df['current_price'] * 1.075) + inbound_postage + hub_freight
    test_df['exp_exit'] = np.maximum(0.01, test_df['current_price'] * (1.0 + test_df['pred_magnitude'] / 100.0))

    # Win scenario
    payout_win_raw = calculate_direct_payout_series(test_df['exp_exit'], clamp_dead_zone=True, is_pro=is_pro)
    kappa_win = calculate_condition_risk_haircut(test_df['exp_exit'], test_df['basis'])
    test_df['payout_win'] = payout_win_raw * kappa_win
    test_df['profit_win'] = test_df['payout_win'] - test_df['basis']
    test_df['roi_win_pct'] = (test_df['profit_win'] / test_df['basis']) * 100.0

    # Fail scenario
    payout_fail_raw = calculate_direct_payout_series(test_df['current_price'], clamp_dead_zone=True, is_pro=is_pro)
    kappa_fail = calculate_condition_risk_haircut(test_df['current_price'], test_df['basis'])
    test_df['payout_fail'] = payout_fail_raw * kappa_fail
    test_df['profit_fail'] = test_df['payout_fail'] - test_df['basis']
    test_df['loss_fail_pct'] = (test_df['profit_fail'] / test_df['basis']) * 100.0

    # Bayesian expectation & Kelly
    p = test_df['move_prob']
    test_df['exp_net_profit'] = (p * test_df['profit_win']) + ((1.0 - p) * test_df['profit_fail'])
    test_df['exp_net_roi_pct'] = (test_df['exp_net_profit'] / test_df['basis']) * 100.0
    b = np.maximum(0.001, test_df['roi_win_pct'] / 100.0)
    a = np.maximum(0.001, np.abs(test_df['loss_fail_pct']) / 100.0)
    test_df['kelly_fraction'] = np.clip((p * b - (1.0 - p) * a) / (a * b), 0.0, 1.0)

    stage1_mask = test_df['move_prob'] >= prob_threshold
    positive_move = test_df['pred_magnitude'] > 0.0
    naive_mask = stage1_mask & positive_move & (test_df['roi_win_pct'] >= min_net_roi_pct)

    if filter_mode == "exp_roi":
        active_mask = stage1_mask & positive_move & (test_df['exp_net_roi_pct'] >= min_net_roi_pct)
    elif filter_mode == "win_roi":
        active_mask = naive_mask
    elif filter_mode == "kelly":
        active_mask = stage1_mask & positive_move & (test_df['kelly_fraction'] > 0.0) & (test_df['roi_win_pct'] >= min_net_roi_pct)
    else:
        active_mask = stage1_mask & positive_move & (test_df['exp_net_roi_pct'] >= min_net_roi_pct)

    sort_columns = {
        "exp_roi": ("exp_net_roi_pct", False),
        "kelly": ("kelly_fraction", False),
        "dollars": ("exp_net_profit", False),
        "win_roi": ("roi_win_pct", False),
    }
    sort_col, sort_asc = sort_columns.get(sort_by, ("exp_net_roi_pct", False))

    buy_signals = test_df[active_mask].copy().sort_values(by=sort_col, ascending=sort_asc)
    naive_signals = test_df[naive_mask].copy().sort_values(by="roi_win_pct", ascending=False)

    if top_daily > 0 and len(buy_signals) > 0:
        buy_signals = (
            buy_signals.groupby('price_date', group_keys=False)
            .apply(lambda g: g.sort_values(by=sort_col, ascending=sort_asc).head(top_daily))
            .reset_index(drop=True)
        )

    buy_signals = evaluate_dataframe_trades(buy_signals, is_pro, sizing)
    naive_signals = evaluate_dataframe_trades(naive_signals, is_pro, sizing="flat")

    total_trades = len(buy_signals)
    win_trades = int(buy_signals['is_win'].sum()) if total_trades > 0 else 0
    loss_trades = total_trades - win_trades
    win_rate = (win_trades / total_trades) * 100.0 if total_trades > 0 else 0.0

    total_capital = float(buy_signals['total_cost'].sum()) if total_trades > 0 else 0.0
    total_net_profit = float(buy_signals['total_profit'].sum()) if total_trades > 0 else 0.0
    portfolio_roi = (total_net_profit / total_capital) * 100.0 if total_capital > 0 else 0.0
    avg_trade_roi = float(buy_signals['net_roi_pct'].mean()) if total_trades > 0 else 0.0
    avg_kelly = float(buy_signals['kelly_fraction'].mean()) if total_trades > 0 else 0.0

    gross_gains = float(buy_signals[buy_signals['total_profit'] > 0]['total_profit'].sum()) if total_trades > 0 else 0.0
    gross_losses = float(abs(buy_signals[buy_signals['total_profit'] < 0]['total_profit'].sum())) if total_trades > 0 else 0.0
    profit_factor = (gross_gains / gross_losses) if gross_losses > 0 else (999.0 if gross_gains > 0 else 0.0)

    active_uuids = set(zip(buy_signals['uuid'], buy_signals['price_date'].dt.strftime('%Y-%m-%d'), buy_signals['finish'])) if total_trades > 0 else set()
    vetoed_trades = naive_signals[
        ~naive_signals.apply(lambda r: (r['uuid'], r['price_date'].strftime('%Y-%m-%d'), r['finish']) in active_uuids, axis=1)
    ].copy() if len(naive_signals) > 0 else pd.DataFrame()

    def determine_veto_reason(row):
        if row['current_price'] < 2.50:
            return "Fee Cliff (Sub-$2.50 Tier)"
        if 2.50 <= row['exp_exit'] <= 2.67:
            return "Dead-Zone [$2.50, $2.67]"
        if row['move_prob'] < 0.92:
            return "Insufficient Prob Margin"
        return "Negative E[Net ROI] Expectation"

    if len(vetoed_trades) > 0:
        vetoed_trades['veto_reason'] = vetoed_trades.apply(determine_veto_reason, axis=1)

    naive_cap = float(naive_signals['total_cost'].sum()) if len(naive_signals) > 0 else 0.0
    naive_prof = float(naive_signals['total_profit'].sum()) if len(naive_signals) > 0 else 0.0
    naive_roi = (naive_prof / naive_cap * 100.0) if naive_cap > 0 else 0.0
    naive_win_rate = (int(naive_signals['is_win'].sum()) / len(naive_signals) * 100.0) if len(naive_signals) > 0 else 0.0

    alpha_cash = total_net_profit - naive_prof
    alpha_roi_bps = (portfolio_roi - naive_roi) * 100.0
    capital_saved = naive_cap - total_capital
    capital_saved_pct = (capital_saved / naive_cap * 100.0) if naive_cap > 0 else 0.0
    vetoed_losses = float(abs(vetoed_trades[vetoed_trades['total_profit'] < 0]['total_profit'].sum())) if len(vetoed_trades) > 0 else 0.0

    all_dates = sorted(list(set(test_df['price_date'].dt.strftime('%Y-%m-%d'))))
    active_by_date = buy_signals.groupby(buy_signals['price_date'].dt.strftime('%Y-%m-%d'))['total_profit'].sum().to_dict() if total_trades > 0 else {}
    naive_by_date = naive_signals.groupby(naive_signals['price_date'].dt.strftime('%Y-%m-%d'))['total_profit'].sum().to_dict() if len(naive_signals) > 0 else {}

    equity_curve = []
    cum_active = 0.0
    cum_naive = 0.0
    for d in all_dates:
        cum_active += active_by_date.get(d, 0.0)
        cum_naive += naive_by_date.get(d, 0.0)
        equity_curve.append({
            "date": d,
            "active_cum_profit": round(cum_active, 2),
            "naive_cum_profit": round(cum_naive, 2)
        })

    def sanitize_trade_records(df_slice):
        if len(df_slice) == 0:
            return []
        out = []
        for _, r in df_slice.iterrows():
            out.append({
                "uuid": r["uuid"],
                "name": r["name"],
                "set_code": r["set_code"],
                "collector_number": str(r["collector_number"]) if r["collector_number"] else None,
                "finish": r["finish"],
                "price_date": str(r["price_date"].date()),
                "current_price": round(float(r["current_price"]), 2),
                "basis": round(float(r["basis"]), 2),
                "realized_exit_payout": round(float(r["realized_exit_payout"]), 2),
                "actual_future_price": round(float(r["actual_future_price"]), 2),
                "pred_magnitude": round(float(r["pred_magnitude"]), 2),
                "move_prob": round(float(r["move_prob"]), 4),
                "kelly_fraction": round(float(r["kelly_fraction"]), 3),
                "allocated_units": int(r["allocated_units"]),
                "total_profit": round(float(r["total_profit"]), 2),
                "net_roi_pct": round(float(r["net_roi_pct"]), 2),
                "is_win": bool(r["is_win"]),
                "veto_reason": r.get("veto_reason", None)
            })
        return out

    payload = {
        "status": "success",
        "params": {
            "min_net_roi_pct": min_net_roi_pct,
            "tau": prob_threshold,
            "filter_mode": filter_mode,
            "sort_by": sort_by,
            "sizing": sizing,
            "top_daily": top_daily,
            "is_pro": is_pro
        },
        "summary": {
            "total_trades": total_trades,
            "win_trades": win_trades,
            "loss_trades": loss_trades,
            "win_rate": round(win_rate, 2),
            "total_capital": round(total_capital, 2),
            "total_net_profit": round(total_net_profit, 2),
            "portfolio_roi": round(portfolio_roi, 2),
            "avg_trade_roi": round(avg_trade_roi, 2),
            "avg_kelly": round(avg_kelly, 3),
            "profit_factor": round(profit_factor, 2),
            "test_start_date": str(test_start_date.date()),
            "test_end_date": str(test_df['price_date'].max().date()),
            "test_universe_count": total_test_universe
        },
        "ablation": {
            "naive_trades": len(naive_signals),
            "naive_win_rate": round(naive_win_rate, 2),
            "naive_capital": round(naive_cap, 2),
            "naive_profit": round(naive_prof, 2),
            "naive_roi": round(naive_roi, 2),
            "alpha_cash": round(alpha_cash, 2),
            "alpha_roi_bps": round(alpha_roi_bps, 1),
            "capital_saved": round(capital_saved, 2),
            "capital_saved_pct": round(capital_saved_pct, 1),
            "vetoed_losses_avoided": round(vetoed_losses, 2)
        },
        "equity_curve": equity_curve,
        "top_trades": sanitize_trade_records(buy_signals.sort_values(by='total_profit', ascending=False).head(8)),
        "worst_trades": sanitize_trade_records(buy_signals[buy_signals['total_profit'] < 0].sort_values(by='total_profit', ascending=True).head(5)),
        "vetoed_traps": sanitize_trade_records(vetoed_trades.sort_values(by='total_profit', ascending=True).head(8))
    }
    if as_dict:
        return payload
    print(f"\nBacktest Complete: {total_trades} trades executed. PnL: ${total_net_profit:+.2f} ({portfolio_roi:+.2f}% ROI).")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tau", "-t", type=float, default=None)
    parser.add_argument("--hurdle", type=float, default=10.0)
    parser.add_argument("--filter", choices=["exp_roi", "win_roi", "kelly"], default="exp_roi")
    parser.add_argument("--sort", choices=["exp_roi", "kelly", "dollars", "win_roi"], default="exp_roi")
    parser.add_argument("--sizing", choices=["flat", "kelly"], default="flat")
    parser.add_argument("--top-daily", type=int, default=0)
    parser.add_argument("--pro", action="store_true")
    args = parser.parse_args()

    run_arbitrage_backtest(
        min_net_roi_pct=args.hurdle,
        tau=args.tau,
        filter_mode=args.filter,
        sort_by=args.sort,
        sizing=args.sizing,
        top_daily=args.top_daily,
        is_pro=args.pro,
        as_dict=False
    )


if __name__ == "__main__":
    main()