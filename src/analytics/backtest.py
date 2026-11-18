import argparse
from pathlib import Path
import sys
from typing import Optional
import duckdb
import pandas as pd

from src.analytics.condition import DEFAULT_CONDITION_POLICY
from src.analytics.inference import (
    BuyerRadarProxyFlipperRule,
    evaluate_direct_flip_frame,
    load_forecast_bundle,
    predict_quantiles,
)
from src.analytics.sizing import FixedCapSizingPolicy, FlatSizingPolicy
from src.cli.reports import render_terminal_scorecard
from src.config import DB_PATH, FEATURE_COLS, MODEL_PATH
from src.pricing.fees import calculate_direct_payout_series


def evaluate_dataframe_trades(
    df: pd.DataFrame, is_pro: bool, sizing: Optional[str] = None
) -> pd.DataFrame:
    required_cols = [
        "allocated_units",
        "actual_future_price",
        "realized_exit_payout",
        "unit_profit",
        "net_roi_pct",
        "is_win",
        "total_cost",
        "total_profit",
    ]
    if len(df) == 0:
        out = df.copy()
        for c in required_cols:
            out[c] = pd.Series(dtype="float64" if c != "is_win" else "bool")
        return out
    out = df.copy()
    if sizing is not None or "allocated_units" not in out.columns:
        allocator = FixedCapSizingPolicy() if sizing == "kelly" else FlatSizingPolicy()
        amihud_col = out["amihud_illiquidity_30d"] if "amihud_illiquidity_30d" in out else None
        out["allocated_units"] = allocator.allocate(
            expected_roi_pct=out["exp_net_roi_pct"],
            lower_bound_return_pct=out["cqr_lpb"],
            basis=out["basis"],
            amihud=amihud_col,
        )

    out["actual_future_price"] = out["current_price"] * (1.0 + out["target_return_7d_pct"] / 100.0)
    raw_realized_payout = calculate_direct_payout_series(
        out["actual_future_price"], clamp_dead_zone=True, is_pro=is_pro
    )
    realized_kappa = DEFAULT_CONDITION_POLICY.evaluate(out["actual_future_price"])

    out["realized_exit_payout"] = raw_realized_payout * realized_kappa
    out["unit_profit"] = out["realized_exit_payout"] - out["basis"]
    out["net_roi_pct"] = (out["unit_profit"] / out["basis"]) * 100.0
    out["is_win"] = out["unit_profit"] > 0
    out["total_cost"] = out["basis"] * out["allocated_units"]
    out["total_profit"] = out["unit_profit"] * out["allocated_units"]
    return out


def run_arbitrage_backtest(
    min_net_roi_pct: float = 8.0,
    tau: float = None,
    filter_mode: str = "cqr_veto",
    sizing: str = "kelly",
    top_daily: int = 0,
    show_ablation: bool = True,
    is_pro: bool = False,
    db_path: Path = DB_PATH,
    model_path: Path = MODEL_PATH,
    as_dict: bool = False,
    top_n_records: int = 8,
):
    if not model_path.exists() or not db_path.exists():
        err_msg = f"Missing database ({db_path}) or model artifact ({model_path})."
        if as_dict:
            raise FileNotFoundError(err_msg)
        print(f"Error: {err_msg}", file=sys.stderr)
        return

    bundle = load_forecast_bundle(model_path)
    prob_threshold = tau if tau is not None else bundle.tau_buyer_radar
    feature_select_sql = ", ".join([f"f.{col}" for col in FEATURE_COLS])
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        query = f"""
            SELECT
                t.uuid, t.finish, t.price_date, t.current_price, t.target_return_7d_pct,
                {feature_select_sql},
                COALESCE(d.name, t.uuid) AS name,
                COALESCE(d.set_code, 'OTC') AS set_code,
                d.collector_number
            FROM fact_training_dataset t
            JOIN fact_card_features f
                ON t.uuid = f.uuid AND t.finish = f.finish AND t.price_date = f.price_date
            LEFT JOIN dim_cards d ON t.uuid = d.uuid
            WHERE t.current_price >= 0.40
            ORDER BY t.price_date ASC
        """
        df = conn.execute(query).fetchdf()
    finally:
        conn.close()

    if len(df) == 0:
        return (
            {"status": "empty", "message": "No historical instances in dataset"}
            if as_dict
            else None
        )

    df["price_date"] = pd.to_datetime(df["price_date"])
    test_start_date = (
        pd.to_datetime(bundle.split_date)
        if bundle.split_date
        else df["price_date"].max() - pd.Timedelta(days=12)
    )
    test_df = df[df["price_date"] >= test_start_date].copy().reset_index(drop=True)

    if len(test_df) == 0:
        return (
            {"status": "empty", "message": f"No records >= {test_start_date.date()}"}
            if as_dict
            else None
        )

    X_test = test_df[list(bundle.feature_cols)].fillna(0.0)
    preds = predict_quantiles(bundle, X_test)
    test_df["move_prob"] = preds.move_prob
    test_df["pred_magnitude"] = preds.q50
    test_df["cqr_lpb"] = preds.q10

    sizing_policy = FixedCapSizingPolicy() if sizing == "kelly" else FlatSizingPolicy()
    test_df = evaluate_direct_flip_frame(test_df, is_pro=is_pro, sizing_policy=sizing_policy)

    rule = BuyerRadarProxyFlipperRule(
        prob_threshold=prob_threshold,
        min_net_roi_pct=min_net_roi_pct,
    )
    gates = rule.evaluate_batch(test_df)
    naive_mask = gates.stage1_spike & gates.roi_hurdle_ok

    if filter_mode in ("exp_roi", "win_roi"):
        active_mask = naive_mask
    else:
        active_mask = gates.stage1_spike & gates.q10_floor_ok & gates.decay_ok & gates.roi_hurdle_ok

    funnel_counts = gates.funnel_counts("Total Test Candidates", include_sizing=False)

    buy_signals = test_df[active_mask].copy()
    naive_signals = test_df[naive_mask].copy()

    if len(buy_signals) > 0:
        buy_signals = buy_signals.sort_values(by="exp_net_roi_pct", ascending=False)
        if top_daily > 0:
            buy_signals = (
                buy_signals.groupby("price_date", group_keys=False)
                .head(top_daily)
                .reset_index(drop=True)
            )

    buy_signals = evaluate_dataframe_trades(buy_signals, is_pro)
    if sizing == "kelly" and len(buy_signals) > 0:
        buy_signals = buy_signals[buy_signals["allocated_units"] > 0].reset_index(drop=True)
    naive_signals = (
        evaluate_dataframe_trades(naive_signals, is_pro, sizing="flat")
        if show_ablation
        else naive_signals.iloc[0:0]
    )

    total_trades = len(buy_signals)
    win_trades = int(buy_signals["is_win"].sum()) if total_trades > 0 else 0
    loss_trades = total_trades - win_trades
    win_rate = (win_trades / total_trades) * 100.0 if total_trades > 0 else 0.0
    total_capital = float(buy_signals["total_cost"].sum()) if total_trades > 0 else 0.0
    total_net_profit = float(buy_signals["total_profit"].sum()) if total_trades > 0 else 0.0
    portfolio_roi = (total_net_profit / total_capital) * 100.0 if total_capital > 0 else 0.0

    def sanitize_trade_records(df_slice):
        if len(df_slice) == 0 or "total_profit" not in df_slice.columns:
            return []
        out = []
        for _, r in df_slice.iterrows():
            out.append(
                {
                    "uuid": r["uuid"],
                    "name": r["name"],
                    "set_code": r["set_code"],
                    "finish": r["finish"],
                    "price_date": str(r["price_date"].date()),
                    "current_price": round(float(r["current_price"]), 2),
                    "basis": round(float(r["basis"]), 2),
                    "realized_exit_payout": round(float(r["realized_exit_payout"]), 2),
                    "actual_future_price": round(float(r["actual_future_price"]), 2),
                    "allocated_units": int(r.get("allocated_units", 1)),
                    "total_profit": round(float(r["total_profit"]), 2),
                    "net_roi_pct": round(float(r["net_roi_pct"]), 2),
                    "is_win": bool(r["is_win"]),
                }
            )
        return out

    top_trades_list = (
        sanitize_trade_records(
            buy_signals.sort_values(by="total_profit", ascending=False).head(top_n_records)
        )
        if total_trades > 0
        else []
    )
    worst_trades_list = (
        sanitize_trade_records(
            buy_signals[buy_signals["total_profit"] < 0]
            .sort_values(by="total_profit", ascending=True)
            .head(top_n_records)
        )
        if total_trades > 0
        else []
    )

    payload = {
        "status": "success",
        "params": {
            "min_net_roi_pct": min_net_roi_pct,
            "tau": prob_threshold,
            "filter_mode": filter_mode,
            "sizing": sizing,
            "top_daily": top_daily,
            "is_pro": is_pro,
        },
        "funnel": funnel_counts,
        "summary": {
            "total_trades": total_trades,
            "win_trades": win_trades,
            "loss_trades": loss_trades,
            "win_rate": round(win_rate, 2),
            "total_capital": round(total_capital, 2),
            "total_net_profit": round(total_net_profit, 2),
            "portfolio_roi": round(portfolio_roi, 2),
            "test_universe_count": len(test_df),
            "test_start_date": str(test_start_date.date()),
            "test_end_date": str(test_df["price_date"].max().date()),
        },
        "ablation": {
            "naive_trades": len(naive_signals),
            "naive_profit": (
                round(float(naive_signals["total_profit"].sum()), 2)
                if len(naive_signals) > 0
                else 0.0
            ),
        },
        "top_trades": top_trades_list,
        "worst_trades": worst_trades_list,
    }

    if not as_dict:
        render_terminal_scorecard(payload)

    return payload


def main():
    parser = argparse.ArgumentParser(description="Tiamat Quant Terminal Backtest Engine")
    parser.add_argument("--hurdle", type=float, default=8.0, help="Minimum net ROI %% hurdle")
    parser.add_argument(
        "--tau",
        type=float,
        default=None,
        help="Spike probability threshold (default: auto from model)",
    )
    parser.add_argument(
        "--sizing", choices=["flat", "kelly"], default="kelly", help="Position sizing model"
    )
    parser.add_argument("--top-daily", type=int, default=0, help="Daily trade cap")
    args = parser.parse_args()

    run_arbitrage_backtest(
        min_net_roi_pct=args.hurdle, tau=args.tau, sizing=args.sizing, top_daily=args.top_daily
    )


if __name__ == "__main__":
    main()
