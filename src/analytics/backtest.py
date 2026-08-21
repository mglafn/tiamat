import sys
import argparse
from pathlib import Path
import duckdb
import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import GradientBoostingRegressor

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


# ---------------------------------------------------------
# Pickled Custom Definitions (Required for joblib.load)
# ---------------------------------------------------------
def custom_asymmetric_objective(y_true, y_pred):
    errors = y_pred - y_true
    alpha = 0.20
    gamma = 5.0
    grad = np.where(errors > 0, 2.0 * (1.0 - alpha + gamma) * errors, 2.0 * alpha * errors)
    hess = np.where(errors > 0, 2.0 * (1.0 - alpha + gamma), 2.0 * alpha)
    return grad, hess


class ConformalizedLowerBoundGenerator:
    def __init__(self, alpha: float = 0.10):
        self.q_lo_model = GradientBoostingRegressor(loss='quantile', alpha=alpha / 2.0, n_estimators=100, random_state=42)
        self.q_hi_model = GradientBoostingRegressor(loss='quantile', alpha=1.0 - (alpha / 2.0), n_estimators=100, random_state=42)
        self.alpha = alpha
        self.q_hat_conformal = None

    def fit_and_calibrate(self, X_train, y_train, X_cal, y_cal):
        self.q_lo_model.fit(X_train, y_train)
        self.q_hi_model.fit(X_train, y_train)
        q_lo_preds = self.q_lo_model.predict(X_cal)
        q_hi_preds = self.q_hi_model.predict(X_cal)
        scores = np.maximum(q_lo_preds - y_cal.to_numpy(), y_cal.to_numpy() - q_hi_preds)
        n = len(y_cal)
        q_level = np.ceil((n + 1) * (1.0 - self.alpha)) / n
        q_level = min(1.0, max(0.0, q_level))
        self.q_hat_conformal = float(np.quantile(scores, q_level, method='higher'))

    def predict_lpb(self, X_test):
        if self.q_hat_conformal is None:
            raise ValueError("CQR model must be calibrated prior to generating lower prediction bounds.")
        raw_q_lo = self.q_lo_model.predict(X_test)
        return raw_q_lo - self.q_hat_conformal


# ---------------------------------------------------------
# Financial & Microstructural Payout Mechanics
# ---------------------------------------------------------
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


def compute_uncertainty_kelly_units(
    expected_roi_pct: pd.Series,
    cqr_lpb: pd.Series,
    basis: pd.Series,
    amihud: pd.Series,
    portfolio_value: float = 10000.0,
    max_position_dollars: float = 50.0,
    kappa_kelly: float = 0.25
) -> pd.Series:
    est_downside = np.maximum(0.05, (expected_roi_pct - cqr_lpb) / 100.0)
    est_upside = np.maximum(0.05, expected_roi_pct / 100.0)
    
    f_kelly = kappa_kelly * (est_upside / np.square(est_downside))
    f_kelly = np.clip(f_kelly, 0.0, 0.05)
    
    dollar_kelly = f_kelly * portfolio_value
    amihud_dollar_cap = 0.02 / np.maximum(amihud, 1e-5)
    
    final_dollar_size = np.minimum(
        dollar_kelly,
        np.minimum(max_position_dollars, amihud_dollar_cap)
    )
    units = np.floor(final_dollar_size / np.maximum(basis, 0.01))
    return np.maximum(1.0, units)


def evaluate_dataframe_trades(df: pd.DataFrame, is_pro: bool, sizing: str) -> pd.DataFrame:
    required_cols = ['allocated_units', 'actual_future_price', 'realized_exit_payout',
                     'unit_profit', 'net_roi_pct', 'is_win', 'total_cost', 'total_profit']
    if len(df) == 0:
        out = df.copy()
        for c in required_cols:
            out[c] = pd.Series(dtype='float64' if c != 'is_win' else 'bool')
        return out

    out = df.copy()
    if sizing == "kelly":
        out['allocated_units'] = compute_uncertainty_kelly_units(
            out['exp_net_roi_pct'],
            out['cqr_lpb'],
            out['basis'],
            out['amihud_illiquidity_30d']
        )
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


# ---------------------------------------------------------
# Terminal Rendering
# ---------------------------------------------------------
def render_terminal_scorecard(payload: dict):
    summary = payload["summary"]
    ablation = payload["ablation"]
    funnel = payload.get("funnel", {})
    top_trades = payload["top_trades"]

    if not HAS_RICH:
        print(f"\nNet PnL: ${summary['total_net_profit']:+,.2f} | ROI: {summary['portfolio_roi']:+.2f}% | Trades: {summary['total_trades']}")
        return

    header = Table.grid(expand=True)
    header.add_column(justify="left", ratio=3)
    header.add_column(justify="right", ratio=2)
    title_text = Text()
    title_text.append("TIAMAT QUANT ARBITRAGE TERMINAL", style="bold cyan")
    title_text.append(" │ ", style="dim white")
    title_text.append("CQR & Risk-Gated Backtest", style="bold white")
    meta_text = Text()
    meta_text.append(f"Window: {summary['test_start_date']} → {summary['test_end_date']}\n", style="dim white")
    meta_text.append(f"Universe: {summary['test_universe_count']:,} cards  ", style="dim white")
    meta_text.append("[Verified 14d Embargo]", style="bold green")
    header.add_row(title_text, meta_text)
    console.print(Panel(header, box=box.ROUNDED, border_style="cyan", padding=(0, 1)))

    # Funnel Table
    if funnel:
        funnel_table = Table(
            box=box.ROUNDED,
            header_style="bold blue",
            border_style="dim",
            expand=True,
            title="[bold white]1. DEFENSIVE SIGNAL FUNNEL[/bold white]"
        )
        funnel_table.add_column("Stage Filter / Gate", style="bold white")
        funnel_table.add_column("Candidates Passing", justify="right", style="cyan")
        funnel_table.add_column("Retention", justify="right", style="dim")
        
        tot = summary['test_universe_count']
        for stage, count in funnel.items():
            pct = f"{(count / tot) * 100:.2f}%" if tot > 0 else "0%"
            funnel_table.add_row(stage, f"{count:,}", pct)
        console.print(funnel_table)
        console.print()

    pnl = summary["total_net_profit"]
    roi = summary["portfolio_roi"]
    win_rate = summary["win_rate"]
    pnl_color = "bold green" if pnl >= 0 else "bold red"
    roi_color = "bold green" if roi >= 0 else "bold red"

    score_table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        expand=True,
        title="[bold white]2. STRATEGY PERFORMANCE SCORECARD[/bold white]"
    )
    score_table.add_column("Net Realized PnL", justify="center")
    score_table.add_column("Portfolio ROI", justify="center")
    score_table.add_column("Win Rate (W / L)", justify="center")
    score_table.add_column("Capital Committed", justify="center")
    score_table.add_row(
        f"[{pnl_color}]${pnl:+,.2f}[/{pnl_color}]",
        f"[{roi_color}]{roi:+.2f}%[/{roi_color}]",
        f"{win_rate:.1f}% ({summary['win_trades']}W / {summary['loss_trades']}L)",
        f"${summary['total_capital']:,.2f}"
    )
    console.print(score_table)
    console.print()

    if len(top_trades) > 0:
        win_table = Table(
            title=f"[bold white]3. EXECUTED TRADES (Showing Top {len(top_trades)})[/bold white]",
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold green",
            expand=True
        )
        win_table.add_column("Date", style="dim")
        win_table.add_column("Card SKU", style="bold white")
        win_table.add_column("Finish", justify="center")
        win_table.add_column("Units", justify="right")
        win_table.add_column("Cost Basis", justify="right")
        win_table.add_column("Realized Exit", justify="right")
        win_table.add_column("Net Profit", justify="right", style="bold green")
        win_table.add_column("Net ROI", justify="right", style="bold green")
        for t in top_trades:
            win_table.add_row(
                t["price_date"],
                f"{t['name']} ({t['set_code']})",
                t["finish"].upper(),
                str(t.get("allocated_units", 1)),
                f"${t['basis']:.2f}",
                f"${t['realized_exit_payout']:.2f}",
                f"${t['total_profit']:+,.2f}",
                f"{t['net_roi_pct']:+.1f}%"
            )
        console.print(win_table)
        console.print()
    else:
        console.print("[dim yellow]ℹ No trades passed all defensive gates in this evaluation window. (Capital 100% preserved)[/dim yellow]\n")


# ---------------------------------------------------------
# Main Backtest Execution
# ---------------------------------------------------------
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
    top_n_records: int = 8
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
    cqr_generator = artifact.get("cqr_generator")
    feature_cols = artifact["feature_cols"]
    metrics = artifact.get("metrics", {})
    prob_threshold = tau if tau is not None else metrics.get("prob_threshold", 0.90)
    persisted_split_date = metrics.get("split_date", None)

    conn = duckdb.connect(str(db_path), read_only=True)
    query = """
        SELECT
            t.uuid, t.finish, t.price_date, t.current_price, t.target_return_7d_pct,
            t.sma_ratio, t.volatility_14d, t.daily_return_pct, t.velocity_7d_pct,
            t.bid_ask_spread_pct, t.spread_velocity_7d, t.vendor_delta_7d,
            t.price_decay_velocity_3d, t.amihud_illiquidity_30d,
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
        return {"status": "empty", "message": "No historical instances in dataset"} if as_dict else None

    df['price_date'] = pd.to_datetime(df['price_date'])
    test_start_date = pd.to_datetime(persisted_split_date) if persisted_split_date else df['price_date'].max() - pd.Timedelta(days=12)
    test_df = df[df['price_date'] >= test_start_date].copy().reset_index(drop=True)

    if len(test_df) == 0:
        return {"status": "empty", "message": f"No records >= {test_start_date.date()}"} if as_dict else None

    X_test = test_df[feature_cols].fillna(0.0)
    test_df['move_prob'] = classifier.predict_proba(X_test)[:, 1]
    test_df['pred_magnitude'] = regressor.predict(X_test)
    
    if cqr_generator:
        test_df['cqr_lpb'] = cqr_generator.predict_lpb(X_test)
    else:
        test_df['cqr_lpb'] = test_df['pred_magnitude'] - 10.0

    inbound_postage = np.where(test_df['current_price'] < 5.00, 0.99, 0.15)
    hub_freight = 0.012
    test_df['basis'] = (test_df['current_price'] * 1.075) + inbound_postage + hub_freight
    test_df['exp_exit'] = np.maximum(0.01, test_df['current_price'] * (1.0 + test_df['pred_magnitude'] / 100.0))

    payout_win_raw = calculate_direct_payout_series(test_df['exp_exit'], clamp_dead_zone=True, is_pro=is_pro)
    kappa_win = calculate_condition_risk_haircut(test_df['exp_exit'], test_df['basis'])
    test_df['payout_win'] = payout_win_raw * kappa_win
    test_df['profit_win'] = test_df['payout_win'] - test_df['basis']
    test_df['roi_win_pct'] = (test_df['profit_win'] / test_df['basis']) * 100.0

    # Model downside failure state (-10% drift)
    assumed_fail_price = test_df['current_price'] * 0.90
    payout_fail_raw = calculate_direct_payout_series(assumed_fail_price, clamp_dead_zone=True, is_pro=is_pro)
    kappa_fail = calculate_condition_risk_haircut(assumed_fail_price, test_df['basis'])
    test_df['payout_fail'] = payout_fail_raw * kappa_fail
    test_df['profit_fail'] = test_df['payout_fail'] - test_df['basis']

    p = test_df['move_prob']
    test_df['exp_net_profit'] = (p * test_df['profit_win']) + ((1.0 - p) * test_df['profit_fail'])
    test_df['exp_net_roi_pct'] = (test_df['exp_net_profit'] / test_df['basis']) * 100.0

    # Defensive Guardrail Funnel
    stage1_mask = (test_df['move_prob'] >= prob_threshold) & (test_df['pred_magnitude'] > 0.0)
    cqr_safety_mask = test_df['cqr_lpb'] >= -15.0  # Statistical lower bound constraint
    decay_filter = test_df['price_decay_velocity_3d'] >= -0.5
    roi_hurdle_mask = test_df['exp_net_roi_pct'] >= min_net_roi_pct

    naive_mask = stage1_mask & (test_df['roi_win_pct'] >= min_net_roi_pct)
    active_mask = stage1_mask & cqr_safety_mask & decay_filter & roi_hurdle_mask

    funnel_counts = {
        "Total Test Candidates": len(test_df),
        "Stage 1 Spike Mover (τ)": int(stage1_mask.sum()),
        "CQR LPB Floor Passed": int((stage1_mask & cqr_safety_mask).sum()),
        "Set Decay Filter Passed": int((stage1_mask & cqr_safety_mask & decay_filter).sum()),
        "Net ROI Hurdle Cleared": int(active_mask.sum())
    }

    buy_signals = test_df[active_mask].copy()
    naive_signals = test_df[naive_mask].copy()

    if len(buy_signals) > 0:
        buy_signals = buy_signals.sort_values(by="exp_net_roi_pct", ascending=False)
        if top_daily > 0:
            buy_signals = buy_signals.groupby('price_date', group_keys=False).apply(lambda g: g.head(top_daily)).reset_index(drop=True)

    buy_signals = evaluate_dataframe_trades(buy_signals, is_pro, sizing)
    naive_signals = evaluate_dataframe_trades(naive_signals, is_pro, sizing="flat")

    total_trades = len(buy_signals)
    win_trades = int(buy_signals['is_win'].sum()) if total_trades > 0 else 0
    loss_trades = total_trades - win_trades
    win_rate = (win_trades / total_trades) * 100.0 if total_trades > 0 else 0.0
    total_capital = float(buy_signals['total_cost'].sum()) if total_trades > 0 else 0.0
    total_net_profit = float(buy_signals['total_profit'].sum()) if total_trades > 0 else 0.0
    portfolio_roi = (total_net_profit / total_capital) * 100.0 if total_capital > 0 else 0.0

    def sanitize_trade_records(df_slice):
        if len(df_slice) == 0 or 'total_profit' not in df_slice.columns:
            return []
        out = []
        for _, r in df_slice.iterrows():
            out.append({
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
                "is_win": bool(r["is_win"])
            })
        return out

    top_trades_list = sanitize_trade_records(buy_signals.sort_values(by='total_profit', ascending=False).head(top_n_records)) if total_trades > 0 else []
    worst_trades_list = sanitize_trade_records(buy_signals[buy_signals['total_profit'] < 0].sort_values(by='total_profit', ascending=True).head(top_n_records)) if total_trades > 0 else []

    payload = {
        "status": "success",
        "params": {
            "min_net_roi_pct": min_net_roi_pct,
            "tau": prob_threshold,
            "filter_mode": filter_mode,
            "sizing": sizing,
            "top_daily": top_daily,
            "is_pro": is_pro
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
            "test_end_date": str(test_df['price_date'].max().date())
        },
        "ablation": {
            "naive_trades": len(naive_signals),
            "naive_profit": round(float(naive_signals['total_profit'].sum()), 2) if len(naive_signals) > 0 else 0.0
        },
        "top_trades": top_trades_list,
        "worst_trades": worst_trades_list
    }

    if not as_dict:
        render_terminal_scorecard(payload)

    return payload


def main():
    parser = argparse.ArgumentParser(description="Tiamat Quant Terminal Backtest Engine")
    parser.add_argument("--hurdle", type=float, default=8.0, help="Minimum net ROI %% hurdle")
    parser.add_argument("--tau", type=float, default=None, help="Spike probability threshold (default: auto from model)")
    parser.add_argument("--sizing", choices=["flat", "kelly"], default="kelly", help="Position sizing model")
    parser.add_argument("--top-daily", type=int, default=0, help="Daily trade cap")
    args = parser.parse_args()

    run_arbitrage_backtest(
        min_net_roi_pct=args.hurdle,
        tau=args.tau,
        sizing=args.sizing,
        top_daily=args.top_daily
    )


if __name__ == "__main__":
    main()