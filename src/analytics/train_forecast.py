"""
src/analytics/train_forecast.py
--------------------------------
Dual-Persona Multi-Quantile XGBoost Predictive Engine.
Simultaneously estimates 10th, 50th, and 90th conditional quantiles with
Isotonic F2.0 calibration for the Buyer Radar, configured via src.config.
"""

import os
import sys
import time
from pathlib import Path
import duckdb
import pandas as pd
import numpy as np
import joblib
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, precision_recall_curve
from sklearn.isotonic import IsotonicRegression

# Ensure repository root is on sys.path for direct script execution
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.config import DB_PATH, MODEL_PATH, MODELS_DIR, MODEL_CONFIG, FEATURE_COLS

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
    from rich.text import Text
    from rich import box
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False

def print_header(db_path: Path, model_output_path: Path):
    if not HAS_RICH:
        print(f"\n--- TIAMAT QUANT TERMINAL │ Multi-Quantile Training Engine ---")
        return
        
    header_grid = Table.grid(expand=True)
    header_grid.add_column(justify="left", ratio=3)
    header_grid.add_column(justify="right", ratio=2)
    
    title = Text()
    title.append("TIAMAT QUANT TERMINAL", style="bold cyan")
    title.append(" │ ", style="dim white")
    title.append("Multi-Quantile Forecasting Engine", style="bold white")
    title.append("\nDual-Persona Topology • Multi-Output Quantiles (q10/q50/q90) • Config-Driven", style="dim italic")
    
    meta = Text()
    meta.append(f"Database: {db_path.name}\n", style="dim cyan")
    meta.append(f"Artifact: {model_output_path.name}  ", style="dim yellow")
    meta.append("[Ready]", style="bold green")
    
    header_grid.add_row(title, meta)
    console.print(Panel(header_grid, box=box.ROUNDED, border_style="cyan", padding=(0, 1)))
    console.print()

def train_dual_persona_engine(db_path: Path = DB_PATH, model_output_path: Path = MODEL_PATH):
    start_time = time.time()
    print_header(db_path, model_output_path)
    
    if not db_path.exists():
        err_msg = f"Database not found at '{db_path}'. Run ETL first."
        if HAS_RICH: console.print(f"[bold red]✖ Error:[/bold red] {err_msg}")
        else: print(f"Error: {err_msg}", file=sys.stderr)
        raise FileNotFoundError(err_msg)

    feature_select_sql = ", ".join([f"f.{col}" for col in FEATURE_COLS])
    
    if HAS_RICH:
        with console.status("[bold cyan]Loading training observations from DuckDB...", spinner="dots"):
            conn = duckdb.connect(str(db_path), read_only=True)
            query = f"""
                SELECT
                    t.price_date, t.current_price, t.target_return_7d_pct,
                    {feature_select_sql}
                FROM fact_training_dataset t
                JOIN fact_card_features f 
                    ON t.uuid = f.uuid AND t.finish = f.finish AND t.price_date = f.price_date
                WHERE t.target_return_7d_pct IS NOT NULL
                  AND t.current_price >= 1.00
                  AND t.target_return_7d_pct BETWEEN -60.0 AND 200.0
            """
            df = conn.execute(query).fetchdf()
            conn.close()
    else:
        conn = duckdb.connect(str(db_path), read_only=True)
        query = f"""
            SELECT
                t.price_date, t.current_price, t.target_return_7d_pct,
                {feature_select_sql}
            FROM fact_training_dataset t
            JOIN fact_card_features f 
                ON t.uuid = f.uuid AND t.finish = f.finish AND t.price_date = f.price_date
            WHERE t.target_return_7d_pct IS NOT NULL
              AND t.current_price >= 1.00
              AND t.target_return_7d_pct BETWEEN -60.0 AND 200.0
        """
        df = conn.execute(query).fetchdf()
        conn.close()

    df['price_date'] = pd.to_datetime(df['price_date'])
    df = df.sort_values('price_date').reset_index(drop=True)
    
    df[FEATURE_COLS] = df[FEATURE_COLS].fillna(0.0)
    target_col = 'target_return_7d_pct'
    
    cfg = MODEL_CONFIG
    
    # Temporal Split with Purged Embargo Buffer
    total_days = (df['price_date'].max() - df['price_date'].min()).days
    test_days = max(7, int(total_days * 0.15))
    val_days = max(7, int(total_days * 0.15))
    embargo_delta = pd.Timedelta(days=cfg['EMBARGO_DAYS'])
    
    test_start_date = df['price_date'].max() - pd.Timedelta(days=test_days)
    val_end_date = test_start_date - embargo_delta
    val_start_date = val_end_date - pd.Timedelta(days=val_days)
    train_cutoff_date = val_start_date - embargo_delta
    
    X = df[FEATURE_COLS]
    y = df[target_col]
    
    train_mask = df['price_date'] <= train_cutoff_date
    val_mask = (df['price_date'] >= val_start_date) & (df['price_date'] <= val_end_date)
    test_mask = df['price_date'] >= test_start_date
    
    X_train, y_train = X.loc[train_mask], y.loc[train_mask]
    X_val, y_val = X.loc[val_mask], y.loc[val_mask]
    X_test, y_test = X.loc[test_mask], y.loc[test_mask]

    if HAS_RICH:
        console.print(f"[bold white]Partition Breakdown:[/bold white] Train: [cyan]{len(X_train):,}[/cyan] | Val: [yellow]{len(X_val):,}[/yellow] | Test: [green]{len(X_test):,}[/green] ({cfg['EMBARGO_DAYS']}D Embargo Protected)\n")

    quantile_models = {}

    if HAS_RICH:
        with Progress(
            SpinnerColumn(spinner_name="dots", style="bold cyan"),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=35, style="dim white", complete_style="bold cyan"),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=False
        ) as progress:
            task = progress.add_task("[cyan]Training Quantile Models...", total=5)
            
            for q in cfg['QUANTILES']:
                progress.update(task, description=f"[bold cyan]Training Quantile Regressor q={q:.2f}...")
                model = xgb.XGBRegressor(
                    objective="reg:quantileerror",
                    quantile_alpha=q,
                    n_estimators=250,
                    learning_rate=0.04,
                    max_depth=5,
                    subsample=0.85,
                    colsample_bytree=0.80,
                    tree_method="hist",
                    random_state=42,
                    n_jobs=4
                )
                model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
                quantile_models[q] = model
                progress.advance(task)
                
            progress.update(task, description=f"[bold cyan]Calibrating Buyer Radar (q_0.90 -> P(Spike >= {cfg['SPIKE_THRESHOLD_PCT']}%))...")
            val_preds_q90 = quantile_models[0.90].predict(X_val)
            y_val_binary = (y_val >= cfg['SPIKE_THRESHOLD_PCT']).astype(int)
            
            isotonic_calibrator = IsotonicRegression(out_of_bounds="clip")
            isotonic_calibrator.fit(val_preds_q90, y_val_binary)
            calibrated_probs_val = isotonic_calibrator.transform(val_preds_q90)
            progress.advance(task)
            
            progress.update(task, description=f"[bold cyan]Optimizing Threshold (F-beta={cfg['F_BETA_RECALL_WEIGHT']:.1f})...")
            precisions, recalls, thresholds = precision_recall_curve(y_val_binary, calibrated_probs_val)
            beta_sq = cfg['F_BETA_RECALL_WEIGHT'] ** 2
            
            f_scores = [
                (1 + beta_sq) * (p * r) / ((beta_sq * p) + r + 1e-8)
                for p, r in zip(precisions, recalls)
            ]
            best_idx = np.argmax(f_scores)
            optimal_tau_buyer = float(thresholds[min(best_idx, len(thresholds) - 1)]) if len(thresholds) > 0 else 0.40
            optimal_tau_buyer = max(0.20, min(0.75, optimal_tau_buyer))
            progress.advance(task)
    else:
        for q in cfg['QUANTILES']:
            print(f"Training Quantile Regressor q={q:.2f}...")
            model = xgb.XGBRegressor(
                objective="reg:quantileerror",
                quantile_alpha=q,
                n_estimators=250,
                learning_rate=0.04,
                max_depth=5,
                subsample=0.85,
                colsample_bytree=0.80,
                tree_method="hist",
                random_state=42,
                n_jobs=4
            )
            model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
            quantile_models[q] = model
            
        val_preds_q90 = quantile_models[0.90].predict(X_val)
        y_val_binary = (y_val >= cfg['SPIKE_THRESHOLD_PCT']).astype(int)
        
        isotonic_calibrator = IsotonicRegression(out_of_bounds="clip")
        isotonic_calibrator.fit(val_preds_q90, y_val_binary)
        calibrated_probs_val = isotonic_calibrator.transform(val_preds_q90)
        
        precisions, recalls, thresholds = precision_recall_curve(y_val_binary, calibrated_probs_val)
        beta_sq = cfg['F_BETA_RECALL_WEIGHT'] ** 2
        f_scores = [(1 + beta_sq) * (p * r) / ((beta_sq * p) + r + 1e-8) for p, r in zip(precisions, recalls)]
        best_idx = np.argmax(f_scores)
        optimal_tau_buyer = float(thresholds[min(best_idx, len(thresholds) - 1)]) if len(thresholds) > 0 else 0.40
        optimal_tau_buyer = max(0.20, min(0.75, optimal_tau_buyer))

    # Out-of-sample evaluation on Holdout Test Set
    test_q10 = quantile_models[0.10].predict(X_test)
    test_q50 = quantile_models[0.50].predict(X_test)
    test_q90 = quantile_models[0.90].predict(X_test)

    # Monotonic Bound Enforcement: Eliminate Quantile Crossing
    test_q10 = np.minimum(test_q10, test_q50)
    test_q90 = np.maximum(test_q90, test_q50)

    test_q50_mae = mean_absolute_error(y_test, test_q50)
    test_calibrated_probs = isotonic_calibrator.transform(test_q90)
    
    flipper_signals = test_q10 >= cfg['FLIPPER_FEE_HURDLE_PCT']
    buyer_radar_signals = test_calibrated_probs >= optimal_tau_buyer
    
    y_test_spikes = (y_test >= cfg['SPIKE_THRESHOLD_PCT']).astype(int)
    buyer_recall = float(y_test_spikes[buyer_radar_signals].sum() / max(1, y_test_spikes.sum())) * 100.0

    if HAS_RICH:
        perf_table = Table(
            title="[bold white]DUAL-PERSONA MODEL EVALUATION DIAGNOSTICS[/bold white]",
            box=box.ROUNDED, header_style="bold magenta", border_style="bright_black", expand=True
        )
        perf_table.add_column("Diagnostic Dimension", style="bold white")
        perf_table.add_column("Holdout Test Metric", justify="right", style="bold green")
        perf_table.add_column("Operational Persona Impact", justify="left", style="cyan")

        perf_table.add_row("Median Forecast MAE (q_0.50)", f"{test_q50_mae:.2f}%", "Symmetric, unskewed baseline for both personas")
        perf_table.add_row(f"Buyer Radar Spike Recall (F{cfg['F_BETA_RECALL_WEIGHT']})", f"{buyer_recall:.1f}%", f"Catches breakouts early (Threshold: τ={optimal_tau_buyer:.3f})")
        perf_table.add_row(f"Flipper High-Conviction Triggers (q_0.10 >= {cfg['FLIPPER_FEE_HURDLE_PCT']}%)", f"{int(flipper_signals.sum()):,} trades", "Conservative capital shield clearing platform fees")
        perf_table.add_row("Buyer Radar Triggers", f"{int(buyer_radar_signals.sum()):,} alerts", "Actionable heads-up on right-tail momentum")

        console.print()
        console.print(perf_table)
        console.print()

    # Save artifact bundle with backward compatibility keys
    model_output_path.parent.mkdir(parents=True, exist_ok=True)

    joblib.dump({
        "quantile_models": quantile_models,
        "isotonic_calibrator": isotonic_calibrator,
        "optimal_tau_buyer": optimal_tau_buyer,
        "regressor": quantile_models[0.50],
        "feature_cols": FEATURE_COLS,
        "metrics": {
            "mae_pct": float(test_q50_mae),
            "prob_threshold": float(optimal_tau_buyer),
            "tau_flipper_hurdle": cfg['FLIPPER_FEE_HURDLE_PCT'],
            "tau_buyer_radar": float(optimal_tau_buyer),
            "split_date": str(test_start_date.date())
        }
    }, model_output_path)

    elapsed = time.time() - start_time
    if HAS_RICH:
        console.print(Panel(
            f"[bold green]✔ Dual-Persona Engine Serialized:[/bold green] {model_output_path} in {elapsed:.1f}s",
            box=box.ROUNDED, border_style="green"
        ))
    else:
        print(f"Model saved to {model_output_path} in {elapsed:.1f}s.")

if __name__ == "__main__":
    train_dual_persona_engine(DB_PATH, MODEL_PATH)