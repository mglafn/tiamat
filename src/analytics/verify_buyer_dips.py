"""
src/analytics/verify_buyer_dips.py
-----------------------------------
Combinatorial Purged Cross-Validation (CPCV) Evaluator for Generalist Buyers.
Evaluates scale-invariant floor detection, true falling knives, and buyer alpha
using tolerances and parameters configured in src.config.
"""

import sys
import itertools
from pathlib import Path
import duckdb
import pandas as pd
import numpy as np
import joblib

# Ensure repository root is on sys.path for direct script execution
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.config import DB_PATH, MODEL_PATH, EVAL_CONFIG, FEATURE_COLS

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

class PurgedGroupTimeSeriesSplitter:
    """
    Combinatorial Purged Cross-Validation (CPCV) Splitter with Purging & Embargo.
    Generates train/test integer index positions with zero target overlap.
    """
    def __init__(
        self,
        n_groups: int = EVAL_CONFIG["CPCV_N_GROUPS"],
        k_test_groups: int = EVAL_CONFIG["CPCV_K_TEST"],
        purge_horizon: int = EVAL_CONFIG["PURGE_HORIZON_DAYS"],
        embargo_pct: float = 0.02
    ):
        self.n_groups = n_groups
        self.k_test_groups = k_test_groups
        self.purge_horizon = purge_horizon
        self.embargo_pct = embargo_pct

    def split(self, df: pd.DataFrame, date_column: str = "price_date"):
        dates = pd.to_datetime(df[date_column]).sort_values().unique()
        T = len(dates)
        embargo_length = max(self.purge_horizon, int(np.floor(self.embargo_pct * T)))
        
        group_bounds = np.array_split(dates, self.n_groups)
        group_indices = list(range(self.n_groups))
        test_combinations = list(itertools.combinations(group_indices, self.k_test_groups))

        for test_groups in test_combinations:
            test_dates_set = set()
            for g in test_groups:
                test_dates_set.update(group_bounds[g])
            
            test_dates = sorted(list(test_dates_set))
            test_start, test_end = test_dates[0], test_dates[-1]

            purge_start = test_start - pd.Timedelta(days=self.purge_horizon)
            embargo_end = test_end + pd.Timedelta(days=embargo_length)

            train_mask = (df[date_column] < purge_start) | (df[date_column] > embargo_end)
            test_mask = df[date_column].isin(test_dates)

            yield np.where(train_mask)[0], np.where(test_mask)[0]

def run_cpcv_buyer_verification(db_path: Path = DB_PATH, model_path: Path = MODEL_PATH):
    if not db_path.exists():
        print(f"Database not found at {db_path}", file=sys.stderr)
        return

    feature_select_sql = ", ".join([f"f.{col}" for col in FEATURE_COLS])
    conn = duckdb.connect(str(db_path), read_only=True)
    query = f"""
        SELECT
            t.uuid, t.finish, t.price_date, t.current_price, t.target_return_7d_pct,
            f.sma_30, f.microstructure_regime,
            {feature_select_sql},
            COALESCE(d.name, t.uuid) AS name,
            COALESCE(d.set_code, 'OTC') AS set_code
        FROM fact_training_dataset t
        JOIN fact_card_features f 
            ON t.uuid = f.uuid AND t.finish = f.finish AND t.price_date = f.price_date
        LEFT JOIN dim_cards d ON t.uuid = d.uuid
        WHERE t.current_price >= 1.00
          AND f.sma_30 IS NOT NULL AND f.sma_30 > 0
        ORDER BY t.price_date ASC
    """
    try:
        df = conn.execute(query).fetchdf()
    except Exception as e:
        conn.close()
        print(f"\n[Database Query Error]: {e}")
        print("Please ensure `python src/analytics/build_features.py` has finished executing.\n")
        return

    conn.close()

    if len(df) == 0:
        print("No records available for backtesting.", file=sys.stderr)
        return

    df['price_date'] = pd.to_datetime(df['price_date'])
    cfg = EVAL_CONFIG

    buyer_radar_available = False
    if model_path.exists():
        try:
            artifact = joblib.load(model_path)
            q_models = artifact.get("quantile_models")
            calibrator = artifact.get("isotonic_calibrator")
            tau_buyer = artifact.get("optimal_tau_buyer", 0.40)

            if q_models and calibrator and 0.90 in q_models:
                buyer_radar_available = True
        except Exception:
            buyer_radar_available = False

    splitter = PurgedGroupTimeSeriesSplitter(
        n_groups=cfg["CPCV_N_GROUPS"],
        k_test_groups=cfg["CPCV_K_TEST"],
        purge_horizon=cfg["PURGE_HORIZON_DAYS"]
    )
    
    total_floor_entries, floor_held, floor_returns = 0, 0, []
    total_knife_vetoes, knife_bleed, knife_returns = 0, 0, []
    total_radar_alerts, radar_spikes, radar_returns = 0, 0, []

    for _, (train_idx, test_idx) in enumerate(splitter.split(df, "price_date")):
        test_df = df.iloc[test_idx].copy()
        if len(test_df) == 0:
            continue

        # Signal 1: Confirmed Floor (Scale-Invariant Deceleration)
        floor_mask = (test_df['microstructure_regime'] == 'CONFIRMED_LOCAL_BOTTOM')
        floors = test_df[floor_mask]
        total_floor_entries += len(floors)
        floor_held += int((floors['target_return_7d_pct'] >= -1.0).sum())
        floor_returns.extend(floors['target_return_7d_pct'].tolist())

        # Signal 2: True Falling Knife (Scale-Invariant Downward Acceleration)
        knife_mask = (test_df['microstructure_regime'] == 'FALLING_KNIFE')
        knives = test_df[knife_mask]
        total_knife_vetoes += len(knives)
        knife_bleed += int((knives['target_return_7d_pct'] < 0.0).sum())
        knife_returns.extend(knives['target_return_7d_pct'].tolist())

        # Signal 3: Buyer Radar Pre-Spike Breakout (Multi-Quantile Upside)
        if buyer_radar_available:
            X_test_sub = test_df[FEATURE_COLS].fillna(0.0)
            preds_q90 = q_models[0.90].predict(X_test_sub)
            calibrated_p = calibrator.transform(preds_q90)
            spike_alerts = test_df[calibrated_p >= tau_buyer]
            total_radar_alerts += len(spike_alerts)
            radar_spikes += int((spike_alerts['target_return_7d_pct'] >= cfg['SPIKE_TARGET_PCT']).sum())
            radar_returns.extend(spike_alerts['target_return_7d_pct'].tolist())

    floor_acc = (floor_held / max(1, total_floor_entries)) * 100.0
    floor_avg = np.mean(floor_returns) if floor_returns else 0.0
    knife_acc = (knife_bleed / max(1, total_knife_vetoes)) * 100.0
    knife_avg = np.mean(knife_returns) if knife_returns else 0.0
    radar_acc = (radar_spikes / max(1, total_radar_alerts)) * 100.0 if total_radar_alerts > 0 else 0.0
    radar_avg = np.mean(radar_returns) if radar_returns else 0.0

    floor_df_all = df[df['microstructure_regime'] == 'CONFIRMED_LOCAL_BOTTOM']
    buyer_alpha = (1.0 - (floor_df_all['current_price'].sum() / floor_df_all['sma_30'].sum())) * 100.0 if len(floor_df_all) > 0 else 0.0
    dar = (np.array(floor_returns) > cfg['DRAWDOWN_TOLERANCE_PCT']).mean() * 100.0 if floor_returns else 0.0
    fir = (np.array(floor_returns) >= cfg['SUPPORT_CUSHION_PCT']).mean() * 100.0 if floor_returns else 0.0

    if not HAS_RICH:
        print(f"CPCV Results across {len(df):,} instances:")
        print(f"Confirmed Floors: {total_floor_entries:,} (Acc: {floor_acc:.1f}%, Avg: {floor_avg:+.2f}%)")
        print(f"Knife Vetoes: {total_knife_vetoes:,} (Acc: {knife_acc:.1f}%, Avg: {knife_avg:+.2f}%)")
        if total_radar_alerts > 0:
            print(f"Radar Alerts: {total_radar_alerts:,} (Acc: {radar_acc:.1f}%, Avg: {radar_avg:+.2f}%)")
        print(f"Buyer Alpha: {buyer_alpha:.2f}% | DAR: {dar:.1f}% | FIR: {fir:.1f}%")
        return

    table = Table(
        title="[bold white]COMBINATORIAL PURGED CROSS-VALIDATION (CPCV) SCORECARD[/bold white]",
        box=box.ROUNDED, header_style="bold cyan", border_style="bright_black", expand=True
    )
    table.add_column("Buyer Decision Signal", style="bold white")
    table.add_column("Trigger Count", justify="right", style="cyan")
    table.add_column("Ground Truth Target", style="dim")
    table.add_column("Empirical Acc (%)", justify="right", style="bold green")
    table.add_column("Avg 7D Realized Move", justify="right", style="bold yellow")

    table.add_row(
        "Confirmed Floor Entry",
        f"{total_floor_entries:,}",
        "Card price held or bounced (Ret >= -1.0%)",
        f"{floor_acc:.1f}%",
        f"{floor_avg:+.2f}%"
    )
    table.add_row(
        "Falling Knife Veto (Wait)",
        f"{total_knife_vetoes:,}",
        "Card continued bleeding (Ret < 0.0%)",
        f"{knife_acc:.1f}%",
        f"{knife_avg:+.2f}%"
    )
    if total_radar_alerts > 0:
        table.add_row(
            "Buyer Radar Breakout Alert",
            f"{total_radar_alerts:,}",
            f"Card realized upward spike (Ret >= +{cfg['SPIKE_TARGET_PCT']}%)",
            f"{radar_acc:.1f}%",
            f"{radar_avg:+.2f}%"
        )

    score_panel = Table(box=box.ROUNDED, border_style="green", expand=True)
    score_panel.add_column("Buyer Alpha (Savings vs 30D SMA)", justify="center", style="bold green")
    score_panel.add_column(f"Floor Integrity Rate (FIR >= {cfg['SUPPORT_CUSHION_PCT']}%)", justify="center", style="bold cyan")
    score_panel.add_column(f"Drawdown Avoidance Rate (DAR > {cfg['DRAWDOWN_TOLERANCE_PCT']}%)", justify="center", style="bold white")
    score_panel.add_row(f"+{buyer_alpha:.2f}%", f"{fir:.1f}%", f"{dar:.1f}%")

    console.print("\n")
    console.print(table)
    console.print()
    console.print(Panel(
        score_panel,
        title="[bold green]WHITE-PAPER SPECIFICATION PERFORMANCE METRICS[/bold green]",
        box=box.ROUNDED,
        border_style="green"
    ))
    console.print()

if __name__ == "__main__":
    run_cpcv_buyer_verification(DB_PATH, MODEL_PATH)