import sys
import argparse
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
import joblib

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.config import DB_PATH, MODEL_PATH, FEATURE_COLS, MODEL_CONFIG, FEE_CONFIG
from src.pricing.fees import calculate_direct_payout_series, landed_basis_series
from src.analytics.condition import evaluate_condition_haircut
from src.analytics.sizing import calculate_position_size

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
        "Stage 1 Spike Mover (τ)": f"Upward right-tail breakout probability (P >= {meta.get('prob_threshold', 0.40):.2f})",
        "q10 Downside Floor Passed": f"10th percentile return floor >= {MODEL_CONFIG['Q10_FLOOR_PCT']:.1f}%",
        "Set Decay Filter Passed": f"Price decay derivative >= {MODEL_CONFIG['DECAY_VELOCITY_FLOOR_PCT']:.2f}%/day (Knife Filter)",
        "Net ROI Hurdle Cleared": f"Expected net ROI >= {meta.get('min_net_roi_pct', MODEL_CONFIG['DEFAULT_ROI_HURDLE_PCT']):.1f}%"
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
    q_models = artifact.get("quantile_models", {})
    calibrator = artifact.get("isotonic_calibrator")
    feature_cols = artifact["feature_cols"]
    metrics = artifact.get("metrics", {})
    # PLACEHOLDER: Uses calibrated buyer spike threshold pending dedicated Flipper entry rule
    prob_threshold = tau if tau is not None else metrics.get("tau_buyer_radar", metrics.get("prob_threshold", 0.40))

    conn = duckdb.connect(str(db_path), read_only=True)
    
    fee = FEE_CONFIG
    spatial_query = f"""
        SELECT
            f.uuid,
            COALESCE(d.name, f.uuid) AS name,
            COALESCE(d.set_code, 'OTC') AS set_code,
            f.finish,
            f.price_date,
            f.tcg_price,
            f.ck_price,
            (
                f.tcg_price * {1.0 + fee['DEFAULT_TAX_RATE']}
                + CASE
                    WHEN f.tcg_price < {fee['INBOUND_POSTAGE_THRESHOLD_USD']} THEN {fee['INBOUND_POSTAGE_LOW_USD']}
                    ELSE {fee['INBOUND_POSTAGE_HIGH_USD']}
                  END
                + {fee['OUTBOUND_BATCH_FREIGHT_USD']}
            ) AS total_acquisition_basis,
            (f.ck_price * {fee['STORE_CREDIT_MULTIPLIER']}) AS ck_store_credit_payout,
            f.price_spread,
            f.spread_pct
        FROM fact_arbitrage_opportunities f
        LEFT JOIN dim_cards d ON f.uuid = d.uuid
        WHERE f.price_spread >= {min_spread}
        ORDER BY f.price_spread DESC
        LIMIT {top_n_records}
    """
    spatial_df = conn.execute(spatial_query).fetchdf()
    
    feature_select_sql = ", ".join([f"f.{col}" for col in FEATURE_COLS])
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
    if q_models and calibrator and all(q in q_models for q in (0.10, 0.50, 0.90)):
        preds_q50 = q_models[0.50].predict(X_live)
        preds_q90 = np.maximum(q_models[0.90].predict(X_live), preds_q50)
        preds_q10 = np.minimum(q_models[0.10].predict(X_live), preds_q50)
        market_df['move_prob'] = calibrator.transform(preds_q90)
        market_df['pred_magnitude'] = preds_q50
        market_df['cqr_lpb'] = preds_q10
    else:
        market_df['move_prob'] = 0.0
        market_df['pred_magnitude'] = 0.0
        market_df['cqr_lpb'] = MODEL_CONFIG["Q10_FLOOR_PCT"]

    market_df['basis'] = landed_basis_series(market_df['current_price'], channel="direct")
    market_df['exp_exit'] = np.maximum(0.01, market_df['current_price'] * (1.0 + market_df['pred_magnitude'] / 100.0))
    
    payout_win_raw = calculate_direct_payout_series(market_df['exp_exit'], clamp_dead_zone=True, is_pro=is_pro)
    kappa_win = evaluate_condition_haircut(market_df['exp_exit'])
    market_df['exp_exit_payout'] = payout_win_raw * kappa_win
    market_df['profit_win'] = market_df['exp_exit_payout'] - market_df['basis']

    market_df['exp_net_profit'] = market_df['profit_win']
    market_df['exp_net_roi_pct'] = (market_df['exp_net_profit'] / market_df['basis']) * 100.0

    # Position sizing:
    if sizing == "kelly":
        market_df['allocated_units'] = calculate_position_size(
            expected_roi_pct=market_df['exp_net_roi_pct'],
            lower_bound_return_pct=market_df['cqr_lpb'],
            basis=market_df['basis'],
            amihud=market_df['amihud_illiquidity_30d']
        )
    else:
        market_df['allocated_units'] = 1.0

    q10_floor = MODEL_CONFIG["Q10_FLOOR_PCT"]
    decay_floor = MODEL_CONFIG["DECAY_VELOCITY_FLOOR_PCT"]
    stage1_mask = (market_df['move_prob'] >= prob_threshold) & (market_df['pred_magnitude'] > 0.0)
    cqr_mask = market_df['cqr_lpb'] >= q10_floor
    decay_mask = market_df['price_decay_velocity_3d'] >= decay_floor
    roi_mask = market_df['exp_net_roi_pct'] >= min_net_roi_pct
    sized_mask = market_df['allocated_units'] > 0
    active_mask = stage1_mask & cqr_mask & decay_mask & roi_mask & sized_mask
    
    funnel_counts = {
        "Total Scanned Active SKUs": len(market_df),
        "Stage 1 Spike Mover (τ)": int(stage1_mask.sum()),
        "q10 Downside Floor Passed": int((stage1_mask & cqr_mask).sum()),
        "Set Decay Filter Passed": int((stage1_mask & cqr_mask & decay_mask).sum()),
        "Net ROI Hurdle Cleared": int(active_mask.sum())
    }
    
    directional_candidates = market_df[active_mask].copy().sort_values(by="exp_net_roi_pct", ascending=False).head(top_n_records)
    trap_mask = stage1_mask & (~active_mask)
    vetoed_df = market_df[trap_mask].copy().sort_values(by="pred_magnitude", ascending=False).head(top_n_records)
    
    def resolve_veto_reason(row):
        if row['cqr_lpb'] < q10_floor:
            return f"Downside Floor Breach ({row['cqr_lpb']:.1f}% < {q10_floor:.1f}%)"
        if row['price_decay_velocity_3d'] < decay_floor:
            return f"Active Falling Knife ({row['price_decay_velocity_3d']:.2f}%/d)"
        if row['exp_net_roi_pct'] < min_net_roi_pct:
            return f"Sub-Hurdle E[ROI] ({row['exp_net_roi_pct']:.1f}% < {min_net_roi_pct:.1f}%)"
        if row['allocated_units'] <= 0:
            return "Exceeds Position Dollar Ceiling"
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