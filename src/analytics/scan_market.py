import os
import sys
import argparse
from pathlib import Path
from decimal import Decimal, ROUND_HALF_EVEN
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
    Guarantees C^2 differentiability across residuals to prevent Newton-Raphson leaf weight 
    instability and hessian discontinuity near zero-error bounds.
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

def render_market_scan_report(payload: dict):
    meta = payload["meta"]
    funnel = payload["funnel"]
    spatial_arbs = payload["spatial_arbitrage"]
    directional_alpha = payload["directional_alpha"]
    vetoed_traps = payload["vetoed_traps"]
    
    if not HAS_RICH:
        print(f"\nTIAMAT MARKET SCAN │ Date: {meta['latest_date']} │ Universe: {meta['scanned_universe']:,} SKUs")
        print(f"Spatial Arbs: {len(spatial_arbs)} | Directional Alpha Signals: {len(directional_alpha)}")
        return
        
    header = Table.grid(expand=True)
    header.add_column(justify="left", ratio=3)
    header.add_column(justify="right", ratio=2)
    
    title_text = Text()
    title_text.append("TIAMAT QUANT ARBITRAGE TERMINAL", style="bold cyan")
    title_text.append(" │ ", style="dim white")
    title_text.append("Live Market Opportunity Scanner", style="bold white")
    title_text.append("\nCross-Venue Spatial Arbitrage & CQR-Gated Directional Alpha", style="dim italic")
    
    meta_text = Text()
    meta_text.append(f"Market Date: {meta['latest_date']}\n", style="dim white")
    meta_text.append(f"Universe: {meta['scanned_universe']:,} Active SKUs  ", style="dim white")
    meta_text.append("[CQR Risk Shield Active]", style="bold green")
    
    header.add_row(title_text, meta_text)
    console.print(Panel(header, box=box.ROUNDED, border_style="cyan", padding=(0, 1)))
    console.print()
    
    funnel_table = Table(
        box=box.ROUNDED,
        header_style="bold blue",
        border_style="bright_black",
        expand=True,
        title="[bold white]1. LIVE DEFENSIVE SIGNAL FUNNEL[/bold white]"
    )
    funnel_table.add_column("Scanning / Vetting Stage", style="bold white")
    funnel_table.add_column("Passing Candidates", justify="right", style="cyan")
    funnel_table.add_column("Funnel Retention", justify="right", style="bold yellow")
    funnel_table.add_column("Gate Constraint", style="dim")
    
    tot = meta['scanned_universe']
    descriptions = {
        "Total Scanned Active SKUs": "Unfiltered live active catalog records",
        "Stage 1 Spike Mover (τ)": f"Upward right-tail breakout probability (P >= {meta.get('prob_threshold', 0.90):.2f})",
        "CQR LPB Floor Passed (≥ -15%)": "Distribution-free conformal lower prediction bound >= -15%",
        "Set Decay Filter Passed (≥ -0.5%/d)": "Price decay derivative >= -0.50%/day (Knife Filter)",
        "Net ROI Hurdle Cleared": f"Expected net ROI >= {meta.get('min_net_roi_pct', 8.0):.1f}%"
    }
    for stage, count in funnel.items():
        pct = f"{(count / tot) * 100:.3f}%" if tot > 0 else "0%"
        desc = descriptions.get(stage, "Analytical filter")
        funnel_table.add_row(stage, f"{count:,}", pct, desc)
        
    console.print(funnel_table)
    console.print()
    
    # 2. Instantaneous Spatial Arbitrage (0-Day Locked Profit)
    if len(spatial_arbs) > 0:
        arb_table = Table(
            title=f"[bold white]2. INSTANTANEOUS SPATIAL ARBITRAGE (Showing Top {len(spatial_arbs)} Locked Spreads)[/bold white]",
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold green",
            expand=True
        )
        arb_table.add_column("Card SKU / Name", style="bold white", max_width=26, overflow="ellipsis")
        arb_table.add_column("Set", justify="center", style="cyan")
        arb_table.add_column("Finish", justify="center", style="yellow")
        arb_table.add_column("TCG Retail", justify="right")
        arb_table.add_column("Landed Cost", justify="right", style="dim")
        arb_table.add_column("CK Credit", justify="right", style="cyan")
        arb_table.add_column("Net Spread", justify="right", style="bold green")
        arb_table.add_column("Spread %", justify="right", style="bold green")
        
        for a in spatial_arbs:
            arb_table.add_row(
                a["name"],
                a["set_code"],
                a["finish"].upper(),
                f"${a['tcg_price']:.2f}",
                f"${a['total_acquisition_basis']:.2f}",
                f"${a['ck_store_credit_payout']:.2f}",
                f"+${a['price_spread']:.2f}",
                f"{a['spread_pct']:+.1f}%"
            )
        console.print(arb_table)
        console.print()
    else:
        console.print("[dim yellow]ℹ No spatial arbitrage spreads cleared acquisition basis and fee hurdles today.[/dim yellow]\n")
        
    if len(directional_alpha) > 0:
        alpha_table = Table(
            title=f"[bold white]3. HIGH-CONVICTION CQR-GATED DIRECTIONAL ALPHA (Showing Top {len(directional_alpha)})[/bold white]",
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold cyan",
            expand=True
        )
        alpha_table.add_column("Card SKU / Name", style="bold white", max_width=24, overflow="ellipsis")
        alpha_table.add_column("Set", justify="center", style="cyan")
        alpha_table.add_column("Finish", justify="center", style="yellow")
        alpha_table.add_column("Close", justify="right")
        alpha_table.add_column("Pred Gain", justify="right", style="yellow")
        alpha_table.add_column("CQR Floor", justify="right", style="green")
        alpha_table.add_column("E[Net ROI]", justify="right", style="bold green")
        alpha_table.add_column("Kelly Units", justify="right", style="bold white")
        alpha_table.add_column("Target Payout", justify="right", style="dim green")
        
        for d in directional_alpha:
            alpha_table.add_row(
                d["name"],
                d["set_code"],
                d["finish"].upper(),
                f"${d['current_price']:.2f}",
                f"{d['pred_magnitude']:+.1f}%",
                f"{d['cqr_lpb']:+.1f}%",
                f"{d['exp_net_roi_pct']:+.1f}%",
                f"{d['allocated_units']} units",
                f"${d['exp_exit_payout']:.2f}"
            )
        console.print(alpha_table)
        console.print()
    else:
        console.print("[dim green]🛡 Defensive Veto Active: No directional signals cleared CQR LPB & decay gates. (Capital 100% Preserved)[/dim green]\n")
        
    if len(vetoed_traps) > 0:
        trap_table = Table(
            title=f"[bold white]4. TOP VETOED VALUE TRAPS (Active Friction & Crash Defense Proof)[/bold white]",
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold magenta",
            expand=True
        )
        trap_table.add_column("Card SKU / Name", style="bold white", max_width=24, overflow="ellipsis")
        trap_table.add_column("Set", justify="center", style="cyan")
        trap_table.add_column("Finish", justify="center", style="yellow")
        trap_table.add_column("Price", justify="right", style="dim")
        trap_table.add_column("ML Pred %", justify="right", style="yellow")
        trap_table.add_column("CQR Floor", justify="right", style="dim")
        trap_table.add_column("Defensive Veto Reason", style="bold magenta")
        
        for t in vetoed_traps:
            trap_table.add_row(
                t["name"],
                t["set_code"],
                t["finish"].upper(),
                f"${t['current_price']:.2f}",
                f"{t['pred_magnitude']:+.1f}%",
                f"{t['cqr_lpb']:+.1f}%",
                t["veto_reason"]
            )
        console.print(trap_table)
        console.print()

def scan_live_market(
    min_net_roi_pct: float = 8.0,
    min_spread: float = 0.0,
    tau: float = None,
    sizing: str = "kelly",
    is_pro: bool = False,
    db_path: Path = DB_PATH,
    model_path: Path = MODEL_PATH,
    top_n_records: int = 8,
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
    cqr_generator = artifact.get("cqr_generator")
    feature_cols = artifact["feature_cols"]
    metrics = artifact.get("metrics", {})
    prob_threshold = tau if tau is not None else metrics.get("prob_threshold", 0.90)
    conn = duckdb.connect(str(db_path), read_only=True)
    spatial_query = """
        SELECT
            f.uuid,
            COALESCE(d.name, f.uuid) AS name,
            COALESCE(d.set_code, 'OTC') AS set_code,
            f.finish,
            f.price_date,
            f.tcg_price,
            f.ck_price,
            (f.tcg_price * 1.075 + CASE WHEN f.tcg_price < 5.00 THEN 0.99 ELSE 0.15 END + 0.012 + 0.09) AS total_acquisition_basis,
            (f.ck_price * 1.30) AS ck_store_credit_payout,
            f.price_spread,
            f.spread_pct
        FROM fact_arbitrage_opportunities f
        LEFT JOIN dim_cards d ON f.uuid = d.uuid
        WHERE f.price_spread >= ?
        ORDER BY f.price_spread DESC
        LIMIT ?
    """
    spatial_df = conn.execute(spatial_query, [float(min_spread), int(top_n_records)]).fetchdf()
    feature_cols_sql = ", ".join([f"f.{col}" for col in feature_cols])
    features_query = f"""
        WITH latest_features AS (
            SELECT
                f.uuid, f.finish, f.price_date, f.current_price,
                {feature_cols_sql},
                COALESCE(d.name, f.uuid) AS name,
                COALESCE(d.set_code, 'OTC') AS set_code
            FROM fact_card_features f
            LEFT JOIN dim_cards d ON f.uuid = d.uuid
            WHERE f.current_price >= 0.40
            QUALIFY ROW_NUMBER() OVER(PARTITION BY f.uuid, f.finish ORDER BY f.price_date DESC) = 1
        )
        SELECT * FROM latest_features
        ORDER BY current_price DESC
    """
    market_df = conn.execute(features_query).fetchdf()
    conn.close()
    if len(market_df) == 0:
        return {"status": "empty", "message": "No active market records found"} if as_dict else None
    X_live = market_df[feature_cols].fillna(0.0)
    if q_models and calibrator and 0.90 in q_models:
        preds_q90 = q_models[0.90].predict(X_live)
        market_df['move_prob'] = calibrator.transform(preds_q90)
        market_df['pred_magnitude'] = q_models[0.50].predict(X_live)
        market_df['cqr_lpb'] = q_models[0.10].predict(X_live)
    elif classifier and regressor:
        market_df['move_prob'] = classifier.predict_proba(X_live)[:, 1]
        market_df['pred_magnitude'] = regressor.predict(X_live)
        market_df['cqr_lpb'] = cqr_generator.predict_lpb(X_live) if cqr_generator else (market_df['pred_magnitude'] - 10.0)
    else:
        market_df['move_prob'] = 0.5
        market_df['pred_magnitude'] = regressor.predict(X_live) if regressor else 0.0
        market_df['cqr_lpb'] = market_df['pred_magnitude'] - 10.0

    market_df['basis'] = compute_landed_basis_series(market_df['current_price'], tax_rate=0.075)
    market_df['exp_exit'] = np.maximum(0.01, market_df['current_price'] * (1.0 + market_df['pred_magnitude'] / 100.0))

    payout_win_raw = calculate_direct_payout_series(market_df['exp_exit'], clamp_dead_zone=True, is_pro=is_pro)
    payout_win_after_freight = np.maximum(0.0, payout_win_raw - OUTBOUND_BATCH_FREIGHT)
    kappa_win = calculate_condition_risk_haircut(market_df['exp_exit'], market_df['basis'])
    market_df['exp_exit_payout'] = payout_win_after_freight * kappa_win
    market_df['profit_win'] = market_df['exp_exit_payout'] - market_df['basis']

    fail_price = market_df['current_price'] * 0.90
    payout_fail_raw = calculate_direct_payout_series(fail_price, clamp_dead_zone=True, is_pro=is_pro)
    payout_fail_after_freight = np.maximum(0.0, payout_fail_raw - OUTBOUND_BATCH_FREIGHT)
    kappa_fail = calculate_condition_risk_haircut(fail_price, market_df['basis'])
    market_df['profit_fail'] = (payout_fail_after_freight * kappa_fail) - market_df['basis']
    p = market_df['move_prob']
    market_df['exp_net_profit'] = (p * market_df['profit_win']) + ((1.0 - p) * market_df['profit_fail'])
    market_df['exp_net_roi_pct'] = (market_df['exp_net_profit'] / market_df['basis']) * 100.0
    if sizing == "kelly":
        market_df['allocated_units'] = compute_uncertainty_kelly_units(
            market_df['exp_net_roi_pct'], market_df['cqr_lpb'], market_df['basis'], market_df['amihud_illiquidity_30d']
        )
    else:
        market_df['allocated_units'] = 1.0
    stage1_mask = (market_df['move_prob'] >= prob_threshold) & (market_df['pred_magnitude'] > 0.0)
    cqr_mask = market_df['cqr_lpb'] >= -15.0
    decay_mask = market_df['price_decay_velocity_3d'] >= -0.5
    roi_mask = market_df['exp_net_roi_pct'] >= min_net_roi_pct
    active_mask = stage1_mask & cqr_mask & decay_mask & roi_mask
    funnel_counts = {
        "Total Scanned Active SKUs": len(market_df),
        "Stage 1 Spike Mover (τ)": int(stage1_mask.sum()),
        "CQR LPB Floor Passed (≥ -15%)": int((stage1_mask & cqr_mask).sum()),
        "Set Decay Filter Passed (≥ -0.5%/d)": int((stage1_mask & cqr_mask & decay_mask).sum()),
        "Net ROI Hurdle Cleared": int(active_mask.sum())
    }
    directional_candidates = market_df[active_mask].copy().sort_values(by="exp_net_roi_pct", ascending=False).head(top_n_records)
    trap_mask = stage1_mask & (~active_mask)
    vetoed_df = market_df[trap_mask].copy().sort_values(by="pred_magnitude", ascending=False).head(top_n_records)
    def resolve_veto_reason(row):
        if row['cqr_lpb'] < -15.0:
            return f"CQR Floor Breach ({row['cqr_lpb']:.1f}% < -15.0%)"
        if row['price_decay_velocity_3d'] < -0.5:
            return f"Active Falling Knife ({row['price_decay_velocity_3d']:.2f}%/d)"
        if row['exp_net_roi_pct'] < min_net_roi_pct:
            return f"Sub-Hurdle E[ROI] ({row['exp_net_roi_pct']:.1f}% < {min_net_roi_pct:.1f}%)"
        return "Microstructural Drag"
    if len(vetoed_df) > 0:
        vetoed_df['veto_reason'] = vetoed_df.apply(resolve_veto_reason, axis=1)
    def sanitize_rows(df_sub):
        if len(df_sub) == 0:
            return []
        out = []
        for _, r in df_sub.iterrows():
            out.append({
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
                "veto_reason": r.get("veto_reason", None)
            })
        return out
    payload = {
        "status": "success",
        "meta": {
            "latest_date": str(market_df['price_date'].max().date()),
            "scanned_universe": len(market_df),
            "prob_threshold": prob_threshold,
            "min_net_roi_pct": min_net_roi_pct
        },
        "funnel": funnel_counts,
        "spatial_arbitrage": spatial_df.to_dict(orient="records"),
        "directional_alpha": sanitize_rows(directional_candidates),
        "vetoed_traps": sanitize_rows(vetoed_df)
    }
    if not as_dict:
        render_market_scan_report(payload)
    return payload

def main():
    parser = argparse.ArgumentParser(
        description="Tiamat Quant Terminal - Live Market Scanner (Spatial & CQR Directional)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--hurdle", type=float, default=8.0, help="Minimum expected net ROI %% hurdle")
    parser.add_argument("--min-spread", type=float, default=0.0, help="Minimum dollar price spread for spatial buylist arb")
    parser.add_argument("--tau", type=float, default=None, help="Spike probability threshold (default: auto from model)")
    parser.add_argument("--sizing", choices=["flat", "kelly"], default="kelly", help="Position sizing model")
    parser.add_argument("--pro", action="store_true", help="Use TCGplayer Pro seller rate card (8.95%%)")
    parser.add_argument("--top", "-n", type=int, default=8, help="Number of records to display in each section")
    args = parser.parse_args()
    
    scan_live_market(
        min_net_roi_pct=args.hurdle,
        min_spread=args.min_spread,
        tau=args.tau,
        sizing=args.sizing,
        is_pro=args.pro,
        top_n_records=args.top
    )

if __name__ == "__main__":
    main()