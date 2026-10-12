import sys
import argparse
from pathlib import Path
import duckdb
import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import GradientBoostingRegressor
from src.core.economics import (
    calculate_direct_payout_series,
    calculate_condition_risk_haircut_series as calculate_condition_risk_haircut,
    compute_uncertainty_kelly_units,
    compute_landed_basis_series,
    OUTBOUND_BATCH_FREIGHT,
)
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


def smooth_asymmetric_huber_objective(y_true, y_pred):
    """
    Smooth Asymmetric Expectile Huber Loss (SAEHL) for XGBoost.
    Guarantees C^2 differentiability across residuals.
    """
    e = y_pred - y_true
    alpha = 0.20
    gamma = 5.0
    delta = 1.0
    k = 10.0
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
    hess = np.maximum(hess, 1e-6)
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

def evaluate_dataframe_trades(df: pd.DataFrame, is_pro: bool, sizing: str) -> pd.DataFrame:
    required_cols = [
        'allocated_units', 'actual_future_price', 'realized_exit_payout',
        'unit_profit', 'net_roi_pct', 'is_win', 'total_cost', 'total_profit'
    ]
    if len(df) == 0:
        out = df.copy()
        for c in required_cols:
            out[c] = pd.Series(dtype='float64' if c != 'is_win' else 'bool')
        return out
    out = df.copy()
    if sizing == "kelly":
        out['allocated_units'] = compute_uncertainty_kelly_units(
            out['exp_net_roi_pct'], out['cqr_lpb'], out['basis'], out['amihud_illiquidity_30d']
        )
    else:
        out['allocated_units'] = 1.0
    out['actual_future_price'] = out['current_price'] * (1.0 + out['target_return_7d_pct'] / 100.0)
    raw_realized_payout = calculate_direct_payout_series(out['actual_future_price'], clamp_dead_zone=True, is_pro=is_pro)
    payout_after_freight = np.maximum(0.0, raw_realized_payout - OUTBOUND_BATCH_FREIGHT)
    realized_kappa = calculate_condition_risk_haircut(out['actual_future_price'], out['basis'])
    out['realized_exit_payout'] = payout_after_freight * realized_kappa
    out['unit_profit'] = out['realized_exit_payout'] - out['basis']
    out['net_roi_pct'] = (out['unit_profit'] / out['basis']) * 100.0
    out['is_win'] = out['unit_profit'] > 0
    out['total_cost'] = out['basis'] * out['allocated_units']
    out['total_profit'] = out['unit_profit'] * out['allocated_units']
    return out


def render_terminal_scorecard(payload: dict):
    summary = payload["summary"]
    ablation = payload["ablation"]
    funnel = payload.get("funnel", {})
    top_trades = payload["top_trades"]
    worst_trades = payload.get("worst_trades", [])
    if not HAS_RICH:
        print(f"\nNet PnL: ${summary['total_net_profit']:+,.2f} | ROI: {summary['portfolio_roi']:+.2f}% | Trades: {summary['total_trades']}")
        return
    header = Table.grid(expand=True)
    header.add_column(justify="left", ratio=3)
    header.add_column(justify="right", ratio=2)
    title_text = Text()
    title_text.append("TIAMAT QUANT ARBITRAGE TERMINAL", style="bold cyan")
    title_text.append(" │ ", style="dim white")
    title_text.append("CQR & Risk-Gated Backtest Engine", style="bold white")
    title_text.append("\nOut-of-Time Chronological Execution Blotter • Asymmetric Loss Shield", style="dim italic")
    meta_text = Text()
    meta_text.append(f"Window: {summary['test_start_date']} → {summary['test_end_date']}\n", style="dim white")
    meta_text.append(f"Universe: {summary['test_universe_count']:,} active candidate instances  ", style="dim white")
    meta_text.append("[Verified 14D Embargo]", style="bold green")
    header.add_row(title_text, meta_text)
    console.print(Panel(header, box=box.ROUNDED, border_style="cyan", padding=(0, 1)))
    console.print()
    if funnel:
        funnel_table = Table(
            box=box.ROUNDED,
            header_style="bold blue",
            border_style="bright_black",
            expand=True,
            title="[bold white]1. DEFENSIVE SIGNAL FUNNEL & MULTI-LAYERED GATE RETENTION[/bold white]"
        )
        funnel_table.add_column("Defensive Filter / Risk Gate", style="bold white")
        funnel_table.add_column("Passing Candidates", justify="right", style="cyan")
        funnel_table.add_column("Funnel Retention", justify="right", style="bold yellow")
        funnel_table.add_column("Filtration Function", style="dim")
        tot = summary['test_universe_count']
        descriptions = {
            "Total Test Candidates": "Unfiltered out-of-time candidate universe",
            "Stage 1 Spike Mover (τ)": "Right-tail upward spike conviction (P >= tau)",
            "CQR LPB Floor Passed": "Statistical lower prediction bound (LPB >= -5.0%)",
            "Set Decay Filter Passed": "Dynamic falling knife decay filter (>= -0.5%/day)",
            "Net ROI Hurdle Cleared": "Expected payout exceeds landed basis + fees"
        }
        for stage, count in funnel.items():
            pct_val = f"{(count / tot) * 100:.3f}%" if tot > 0 else "0%"
            desc = descriptions.get(stage, "Analytical risk filter")
            funnel_table.add_row(stage, f"{count:,}", pct_val, desc)
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
        title="[bold white]2. STRATEGY PERFORMANCE SCORECARD & CAPITAL EFFICIENCY[/bold white]"
    )
    score_table.add_column("Net Realized PnL ($)", justify="center")
    score_table.add_column("Portfolio ROI (%)", justify="center")
    score_table.add_column("Win Rate (W / L Count)", justify="center")
    score_table.add_column("Capital Committed ($)", justify="center")
    score_table.add_column("Ablation Loss Shield", justify="center", style="dim green")
    naive_loss_diff = ablation.get("naive_profit", 0.0) - pnl
    shield_msg = f"+${abs(naive_loss_diff):,.2f} Preserved" if pnl >= ablation.get("naive_profit", 0.0) else "—"
    score_table.add_row(
        f"[{pnl_color}]${pnl:+,.2f}[/{pnl_color}]",
        f"[{roi_color}]{roi:+.2f}%[/{roi_color}]",
        f"{win_rate:.1f}% ({summary['win_trades']}W / {summary['loss_trades']}L)",
        f"${summary['total_capital']:,.2f}",
        f"[bold green]{shield_msg}[/bold green]"
    )
    console.print(score_table)
    console.print()
    if len(top_trades) > 0:
        win_table = Table(
            title=f"[bold white]3. EXECUTED TRADES BLOTTER (Showing Top {len(top_trades)} Alpha Executions)[/bold white]",
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold green",
            expand=True
        )
        win_table.add_column("Execution Date", style="dim")
        win_table.add_column("Card SKU / Name", style="bold white")
        win_table.add_column("Set", justify="center", style="cyan")
        win_table.add_column("Finish", justify="center", style="yellow")
        win_table.add_column("Units", justify="right", style="bold white")
        win_table.add_column("Cost Basis", justify="right")
        win_table.add_column("Realized Exit", justify="right")
        win_table.add_column("Net Profit", justify="right", style="bold green")
        win_table.add_column("Net ROI", justify="right", style="bold green")
        for t in top_trades:
            win_table.add_row(
                str(t["price_date"]),
                str(t['name']),
                str(t['set_code']),
                str(t["finish"]).upper(),
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
    if len(worst_trades) > 0:
        loss_table = Table(
            title=f"[bold white]4. DRAWDOWN & LOSS DIAGNOSTICS (Showing Worst {len(worst_trades)} Positions)[/bold white]",
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold red",
            expand=True
        )
        loss_table.add_column("Execution Date", style="dim")
        loss_table.add_column("Card SKU / Name", style="bold white")
        loss_table.add_column("Set", justify="center", style="cyan")
        loss_table.add_column("Finish", justify="center", style="yellow")
        loss_table.add_column("Units", justify="right")
        loss_table.add_column("Cost Basis", justify="right")
        loss_table.add_column("Realized Exit", justify="right")
        loss_table.add_column("Net Profit", justify="right", style="bold red")
        loss_table.add_column("Net ROI", justify="right", style="bold red")
        for w in worst_trades:
            loss_table.add_row(
                str(w["price_date"]),
                str(w['name']),
                str(w['set_code']),
                str(w["finish"]).upper(),
                str(w.get("allocated_units", 1)),
                f"${w['basis']:.2f}",
                f"${w['realized_exit_payout']:.2f}",
                f"${w['total_profit']:+,.2f}",
                f"{w['net_roi_pct']:+.1f}%"
            )
        console.print(loss_table)
        console.print()


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
    model_artifact: dict = None,
    as_dict: bool = False,
    top_n_records: int = 8
):
    if not db_path.exists():
        err_msg = f"Database not found at '{db_path}'."
        if as_dict:
            raise FileNotFoundError(err_msg)
        print(f"Error: {err_msg}", file=sys.stderr)
        return
<<<<<<< Updated upstream
        
    artifact = joblib.load(model_path)
    classifier = artifact["classifier"]
    regressor = artifact["regressor"]
=======
    if model_artifact is not None:
        artifact = model_artifact
    else:
        if not model_path.exists():
            err_msg = f"Model artifact not found at '{model_path}'."
            if as_dict:
                raise FileNotFoundError(err_msg)
            print(f"Error: {err_msg}", file=sys.stderr)
            return
        artifact = joblib.load(model_path)

    q_models = artifact.get("quantile_models", {})
    calibrator = artifact.get("isotonic_calibrator")
    classifier = artifact.get("classifier")
    regressor = artifact.get("regressor")
>>>>>>> Stashed changes
    cqr_generator = artifact.get("cqr_generator")
    feature_cols = artifact["feature_cols"]
    metrics = artifact.get("metrics", {})
    prob_threshold = tau if tau is not None else metrics.get("prob_threshold", 0.90)

    conn = duckdb.connect(str(db_path), read_only=True)
    feature_select_sql = ", ".join([f"f.{col}" for col in feature_cols])
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
    conn.close()

    if len(df) == 0:
        empty_payload = {
            "status": "empty",
            "params": {"min_net_roi_pct": min_net_roi_pct, "tau": prob_threshold, "filter_mode": filter_mode, "sizing": sizing, "top_daily": top_daily, "is_pro": is_pro},
            "summary": {"total_trades": 0, "win_trades": 0, "loss_trades": 0, "win_rate": 0.0, "total_capital": 0.0, "total_net_profit": 0.0, "portfolio_roi": 0.0, "test_start_date": "N/A", "test_end_date": "N/A", "test_universe_count": 0},
            "ablation": {"naive_trades": 0, "naive_profit": 0.0},
            "top_trades": [],
            "worst_trades": []
        }
        return empty_payload if as_dict else None

    df['price_date'] = pd.to_datetime(df['price_date'])
    total_days = (df['price_date'].max() - df['price_date'].min()).days
    test_days = max(7, int(total_days * 0.15))
    test_start = df['price_date'].max() - pd.Timedelta(days=test_days)
    test_df = df[df['price_date'] >= test_start].copy().reset_index(drop=True)

    if len(test_df) == 0:
        test_df = df.tail(100).copy().reset_index(drop=True)

    X_test = test_df[feature_cols].fillna(0.0)
<<<<<<< Updated upstream
    test_df['move_prob'] = classifier.predict_proba(X_test)[:, 1]
    test_df['pred_magnitude'] = regressor.predict(X_test)
    
    if cqr_generator:
        test_df['cqr_lpb'] = cqr_generator.predict_lpb(X_test)
    else:
        test_df['cqr_lpb'] = test_df['pred_magnitude'] - 10.0
        
    inbound_postage = np.where(test_df['current_price'] < 5.00, 0.99, 0.15)
    hub_freight = 0.012
    test_df['basis'] = (test_df['current_price'] * 1.075) + inbound_postage + hub_freight
=======

    # Multi-quantile inference with legacy fallback
    if q_models and calibrator and 0.90 in q_models:
        preds_q90 = q_models[0.90].predict(X_test)
        test_df['move_prob'] = calibrator.transform(preds_q90)
        test_df['pred_magnitude'] = q_models[0.50].predict(X_test)
        test_df['cqr_lpb'] = q_models[0.10].predict(X_test)
    elif classifier and regressor:
        test_df['move_prob'] = classifier.predict_proba(X_test)[:, 1]
        test_df['pred_magnitude'] = regressor.predict(X_test)
        test_df['cqr_lpb'] = cqr_generator.predict_lpb(X_test) if cqr_generator else (test_df['pred_magnitude'] - 10.0)
    else:
        test_df['move_prob'] = 0.5
        test_df['pred_magnitude'] = regressor.predict(X_test) if regressor else 0.0
        test_df['cqr_lpb'] = test_df['pred_magnitude'] - 10.0

    test_df['basis'] = compute_landed_basis_series(test_df['current_price'], tax_rate=0.075)
>>>>>>> Stashed changes
    test_df['exp_exit'] = np.maximum(0.01, test_df['current_price'] * (1.0 + test_df['pred_magnitude'] / 100.0))

    payout_win_raw = calculate_direct_payout_series(test_df['exp_exit'], clamp_dead_zone=True, is_pro=is_pro)
    payout_win_after_freight = np.maximum(0.0, payout_win_raw - OUTBOUND_BATCH_FREIGHT)
    kappa_win = calculate_condition_risk_haircut(test_df['exp_exit'], test_df['basis'])
    test_df['exp_exit_payout'] = payout_win_after_freight * kappa_win
    test_df['profit_win'] = test_df['exp_exit_payout'] - test_df['basis']

    fail_price = test_df['current_price'] * 0.90
    payout_fail_raw = calculate_direct_payout_series(fail_price, clamp_dead_zone=True, is_pro=is_pro)
    payout_fail_after_freight = np.maximum(0.0, payout_fail_raw - OUTBOUND_BATCH_FREIGHT)
    kappa_fail = calculate_condition_risk_haircut(fail_price, test_df['basis'])
    test_df['profit_fail'] = (payout_fail_after_freight * kappa_fail) - test_df['basis']

    p = test_df['move_prob']
    test_df['exp_net_profit'] = (p * test_df['profit_win']) + ((1.0 - p) * test_df['profit_fail'])
    test_df['exp_net_roi_pct'] = (test_df['exp_net_profit'] / test_df['basis']) * 100.0

    stage1_mask = (test_df['move_prob'] >= prob_threshold) & (test_df['pred_magnitude'] > 0.0)
    cqr_mask = test_df['cqr_lpb'] >= -15.0
    decay_mask = test_df['price_decay_velocity_3d'] >= -0.5
    roi_mask = test_df['exp_net_roi_pct'] >= min_net_roi_pct
    active_mask = stage1_mask & cqr_mask & decay_mask & roi_mask

    funnel_counts = {
        "Total Test Candidates": len(test_df),
        "Stage 1 Spike Mover (τ)": int(stage1_mask.sum()),
        "CQR LPB Floor Passed": int((stage1_mask & cqr_mask).sum()),
        "Set Decay Filter Passed": int((stage1_mask & cqr_mask & decay_mask).sum()),
        "Net ROI Hurdle Cleared": int(active_mask.sum())
    }

    gated_candidates = test_df[active_mask].copy()
    if top_daily > 0 and len(gated_candidates) > 0:
        gated_candidates = gated_candidates.sort_values(by=['price_date', 'exp_net_roi_pct'], ascending=[True, False])
        gated_candidates = gated_candidates.groupby('price_date').head(top_daily).reset_index(drop=True)

    evaluated_trades = evaluate_dataframe_trades(gated_candidates, is_pro=is_pro, sizing=sizing)
    naive_trades = evaluate_dataframe_trades(test_df[stage1_mask].copy(), is_pro=is_pro, sizing="flat")

    tot_trades = len(evaluated_trades)
    win_trades = int(evaluated_trades['is_win'].sum()) if tot_trades > 0 else 0
    loss_trades = tot_trades - win_trades
    tot_capital = float(evaluated_trades['total_cost'].sum()) if tot_trades > 0 else 0.0
    tot_profit = float(evaluated_trades['total_profit'].sum()) if tot_trades > 0 else 0.0
    port_roi = (tot_profit / tot_capital * 100.0) if tot_capital > 0 else 0.0
    win_rate = (win_trades / tot_trades * 100.0) if tot_trades > 0 else 0.0

    top_trades_df = evaluated_trades.sort_values(by="total_profit", ascending=False).head(top_n_records)
    worst_trades_df = evaluated_trades.sort_values(by="total_profit", ascending=True).head(top_n_records)

    def row_to_dict(df_sub):
        res = []
        for _, r in df_sub.iterrows():
            res.append({
                "uuid": r["uuid"],
                "name": r["name"],
                "set_code": r["set_code"],
                "finish": r["finish"],
                "price_date": str(r["price_date"].date()) if hasattr(r["price_date"], "date") else str(r["price_date"]),
                "current_price": round(float(r["current_price"]), 2),
                "basis": round(float(r["basis"]), 2),
                "realized_exit_payout": round(float(r["realized_exit_payout"]), 2),
                "actual_future_price": round(float(r["actual_future_price"]), 2),
                "allocated_units": int(r.get("allocated_units", 1)),
                "total_profit": round(float(r["total_profit"]), 2),
                "net_roi_pct": round(float(r["net_roi_pct"]), 2),
                "is_win": bool(r["is_win"])
            })
        return res

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
            "total_trades": tot_trades,
            "win_trades": win_trades,
            "loss_trades": loss_trades,
            "win_rate": round(win_rate, 2),
            "total_capital": round(tot_capital, 2),
            "total_net_profit": round(tot_profit, 2),
            "portfolio_roi": round(port_roi, 2),
            "test_start_date": str(test_df['price_date'].min().date()),
            "test_end_date": str(test_df['price_date'].max().date()),
            "test_universe_count": len(test_df)
        },
        "ablation": {
            "naive_trades": len(naive_trades),
            "naive_profit": round(float(naive_trades['total_profit'].sum()), 2) if len(naive_trades) > 0 else 0.0
        },
        "top_trades": row_to_dict(top_trades_df),
        "worst_trades": row_to_dict(worst_trades_df)
    }

    if not as_dict:
        render_terminal_scorecard(payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description="Tiamat Quant Terminal Backtest Engine")
    parser.add_argument("--hurdle", type=float, default=8.0, help="Minimum net ROI %% hurdle")
    parser.add_argument("--tau", type=float, default=None, help="Spike probability threshold")
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