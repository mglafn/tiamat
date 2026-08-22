import os
import sys
import time
from pathlib import Path
import duckdb
import pandas as pd
import numpy as np
import joblib
from xgboost import XGBRegressor, XGBClassifier
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.ensemble import GradientBoostingRegressor
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.text import Text
from rich import box

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"
MODEL_DIR = BASE_DIR / "models"

console = Console()

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
    
    # Sigmoid smoothing and derivatives
    sig = 1.0 / (1.0 + np.exp(-k * e))
    dsig = k * sig * (1.0 - sig)
    ddsig = k * k * sig * (1.0 - sig) * (1.0 - 2.0 * sig)
    
    # Asymmetric Weight w_k(e) and derivatives
    scale_factor = 1.0 - 2.0 * alpha + gamma
    w = alpha + scale_factor * sig
    dw = scale_factor * dsig
    ddw = scale_factor * ddsig
    
    # Pseudo-Huber Loss l_delta(e) and derivatives
    u = e / delta
    sqrt_term = np.sqrt(1.0 + u**2)
    l_huber = 2.0 * (delta**2) * (sqrt_term - 1.0)
    dl_huber = 2.0 * e / sqrt_term
    ddl_huber = 2.0 / (sqrt_term**3)
    
    # Analytical Gradient g_i and Hessian h_i
    grad = dw * l_huber + w * dl_huber
    hess = ddw * l_huber + 2.0 * dw * dl_huber + w * ddl_huber
    
    # Guarantee numerical floor on Hessian to prevent division by zero
    hess = np.maximum(hess, 1e-6)
    
    return grad, hess

class ConformalizedLowerBoundGenerator:
    def __init__(self, alpha: float = 0.10):
        self.q_lo_model = GradientBoostingRegressor(loss='quantile', alpha=alpha / 2.0, n_estimators=100, random_state=42)
        self.q_hi_model = GradientBoostingRegressor(loss='quantile', alpha=1.0 - (alpha / 2.0), n_estimators=100, random_state=42)
        self.alpha = alpha
        self.q_hat_conformal = None

    def fit_and_calibrate(self, X_train: pd.DataFrame, y_train: pd.Series, X_cal: pd.DataFrame, y_cal: pd.Series):
        self.q_lo_model.fit(X_train, y_train)
        self.q_hi_model.fit(X_train, y_train)
        q_lo_preds = self.q_lo_model.predict(X_cal)
        q_hi_preds = self.q_hi_model.predict(X_cal)
        
        scores = np.maximum(q_lo_preds - y_cal.to_numpy(), y_cal.to_numpy() - q_hi_preds)
        n = len(y_cal)
        q_level = np.ceil((n + 1) * (1.0 - self.alpha)) / n
        q_level = min(1.0, max(0.0, q_level))
        
        self.q_hat_conformal = float(np.quantile(scores, q_level, method='higher'))

    def predict_lpb(self, X_test: pd.DataFrame) -> np.ndarray:
        if self.q_hat_conformal is None:
            raise ValueError("CQR model must be calibrated prior to generating lower prediction bounds.")
        raw_q_lo = self.q_lo_model.predict(X_test)
        return raw_q_lo - self.q_hat_conformal

def print_header(db_path: str, model_output_dir: str):
    header_grid = Table.grid(expand=True)
    header_grid.add_column(justify="left", ratio=3)
    header_grid.add_column(justify="right", ratio=2)
    
    title = Text()
    title.append("TIAMAT QUANT ARBITRAGE TERMINAL", style="bold cyan")
    title.append(" │ ", style="dim white")
    title.append("ML Forecasting Engine Trainer", style="bold white")
    title.append("\nTwo-Stage Hurdle Architecture • Smooth Asymmetric Loss • CQR LPB Bounds", style="dim italic")
    
    meta = Text()
    meta.append(f"Database: {db_path}\n", style="dim cyan")
    meta.append(f"Artifacts: {model_output_dir}  ", style="dim yellow")
    meta.append("[Ready]", style="bold green")
    
    header_grid.add_row(title, meta)
    console.print(Panel(header_grid, box=box.ROUNDED, border_style="cyan", padding=(0, 1)))
    console.print()

def print_split_table(splits_data: dict, total_records: int):
    table = Table(
        title="[bold white]1. TEMPORAL PARTITION & EMBARGO TOPOLOGY[/bold white]",
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="bright_black",
        expand=True
    )
    table.add_column("Partition Segment", style="bold white", width=22)
    table.add_column("Date Range", style="yellow", justify="center")
    table.add_column("Observations", justify="right")
    table.add_column("Universe Share", justify="right")
    table.add_column("Breakouts (≥ +12%)", justify="right", style="bold green")
    
    for name, s in splits_data.items():
        if s.get("is_embargo"):
            table.add_row(
                f"[dim italic]🛡 {name}[/dim italic]",
                f"[dim]{s['range']}[/dim]",
                "[dim]—[/dim]",
                "[dim]—[/dim]",
                "[dim italic]14D Embargo Guard[/dim italic]"
            )
        else:
            share = f"{(s['count'] / total_records) * 100:.1f}%" if total_records else "0%"
            movers = f"{s['movers']:,} ({s['movers_pct']:.1f}%)" if s['count'] > 0 else "—"
            table.add_row(name, s['range'], f"{s['count']:,}", share, movers)
            
    console.print(table)
    console.print()

def print_post_training_report(metrics_dict: dict, classifier, regressor, feature_cols, X_val, y_val, X_test, y_test, cqr_gen):
    val_probs = classifier.predict_proba(X_val)[:, 1]
    val_mags = regressor.predict(X_val)
    opt_val_preds = np.where(val_probs >= metrics_dict['prob_threshold'], val_mags, 0.0)
    
    val_base_mae = mean_absolute_error(y_val, val_mags)
    val_opt_mae = mean_absolute_error(y_val, opt_val_preds)
    
    val_lpb = cqr_gen.predict_lpb(X_val)
    val_coverage = np.mean(y_val.to_numpy() >= val_lpb) * 100.0
    val_active_count = int(np.sum(val_probs >= metrics_dict['prob_threshold']))
    val_active_pct = (val_active_count / len(X_val)) * 100.0 if len(X_val) > 0 else 0.0
    
    test_probs = classifier.predict_proba(X_test)[:, 1]
    test_mags = regressor.predict(X_test)
    opt_test_preds = np.where(test_probs >= metrics_dict['prob_threshold'], test_mags, 0.0)
    
    test_base_mae = mean_absolute_error(y_test, test_mags)
    test_opt_mae = mean_absolute_error(y_test, opt_test_preds)
    
    test_lpb = cqr_gen.predict_lpb(X_test)
    test_coverage = np.mean(y_test.to_numpy() >= test_lpb) * 100.0
    test_active_count = int(np.sum(test_probs >= metrics_dict['prob_threshold']))
    test_active_pct = (test_active_count / len(X_test)) * 100.0 if len(X_test) > 0 else 0.0
    
    test_active_mask = (test_probs >= metrics_dict['prob_threshold']) & (opt_test_preds > 0.0)
    test_dir_acc = (
        float(np.mean(y_test.to_numpy()[test_active_mask] > 0.0) * 100.0)
        if np.sum(test_active_mask) > 0
        else 0.0
    )
    
    perf_table = Table(
        title="[bold white]2. MODEL EVALUATION & CONFORMAL COVERAGE DIAGNOSTICS[/bold white]",
        box=box.ROUNDED,
        header_style="bold magenta",
        border_style="bright_black",
        expand=True
    )
    perf_table.add_column("Diagnostic Performance Metric", style="bold white")
    perf_table.add_column("Validation Partition", justify="right", style="cyan")
    perf_table.add_column("Out-of-Sample Test Set", justify="right", style="bold green")
    perf_table.add_column("Benchmark / Theoretical Baseline", justify="right", style="dim")
    
    mae_delta_val = ((val_base_mae - val_opt_mae) / val_base_mae) * 100.0
    mae_delta_test = ((test_base_mae - test_opt_mae) / test_base_mae) * 100.0
    
    perf_table.add_row(
        "Hurdle-Gated Forecast MAE",
        f"[bold]{val_opt_mae:.3f}%[/bold] ([green]-{mae_delta_val:.1f}%[/green])",
        f"[bold]{test_opt_mae:.3f}%[/bold] ([green]-{mae_delta_test:.1f}%[/green])",
        f"Raw Un-Gated Regressor: {test_base_mae:.3f}%"
    )
    perf_table.add_row(
        "CQR Coverage Guarantee (Target: 90.0%)",
        f"{val_coverage:.2f}%",
        f"[bold green]{test_coverage:.2f}%[/bold green]",
        f"Calibrated Conformal Score q̂: {cqr_gen.q_hat_conformal:.3f}"
    )
    perf_table.add_row(
        "Filtered Execution Trigger Volume",
        f"{val_active_count:,} / {len(X_val):,} ({val_active_pct:.2f}%)",
        f"{test_active_count:,} / {len(X_test):,} ({test_active_pct:.2f}%)",
        "Selective Right-Tail Signals Only"
    )
    perf_table.add_row(
        "Active Signal Directional Win Rate",
        "—",
        f"[bold green]{test_dir_acc:.1f}%[/bold green]",
        "Target Realized Return > 0.0%"
    )
    perf_table.add_row(
        "Optimal Hurdle Conviction Threshold (τ)",
        f"{metrics_dict['prob_threshold']:.4f}",
        "—",
        "MAE Minimum over [0.50, 0.98]"
    )
    perf_table.add_row(
        "Epistemic Variance Baseline (σ²)",
        f"{metrics_dict['epistemic_var_baseline']:.4f}",
        "—",
        "Ensemble Sub-Sample Dispersion"
    )
    
    console.print(perf_table)
    console.print()
    
    clf_imp = pd.Series(classifier.feature_importances_, index=feature_cols).sort_values(ascending=False).head(5)
    reg_imp = pd.Series(regressor.feature_importances_, index=feature_cols).sort_values(ascending=False).head(5)
    
    feat_table = Table(
        title="[bold white]3. FEATURE GAIN ATTRIBUTION (Top 5 Predictor Weights)[/bold white]",
        box=box.ROUNDED,
        header_style="bold yellow",
        border_style="bright_black",
        expand=True
    )
    feat_table.add_column("Rank", justify="center", width=6, style="dim")
    feat_table.add_column("Stage 1 Spike Classifier Gate", style="cyan")
    feat_table.add_column("Clf Gain", justify="right", style="cyan")
    feat_table.add_column("Stage 2 Magnitude SAEHL Regressor", style="yellow")
    feat_table.add_column("Reg Gain", justify="right", style="yellow")
    
    for i in range(5):
        feat_table.add_row(
            f"#{i+1}",
            clf_imp.index[i],
            f"{clf_imp.values[i]:.4f}",
            reg_imp.index[i],
            f"{reg_imp.values[i]:.4f}"
        )
    console.print(feat_table)
    console.print()

def train_xgboost_forecast(db_path: str, model_output_dir: str):
    start_time = time.time()
    print_header(db_path, model_output_dir)
    
    if not Path(db_path).exists():
        console.print(f"[bold red]✖ Error:[/bold red] Database not found at '{db_path}'. Run ETL first.")
        raise FileNotFoundError(f"Database not found at '{db_path}'. Run ETL first.")
        
    with console.status("[bold cyan]Querying DuckDB fact dataset...", spinner="dots"):
        conn = duckdb.connect(db_path, read_only=True)
        query = """
            SELECT
                price_date, sma_ratio, volatility_14d, daily_return_pct, velocity_7d_pct,
                bid_ask_spread_pct, spread_velocity_7d, vendor_delta_7d, price_decay_velocity_3d,
                amihud_illiquidity_30d, is_foil, is_reserved, mana_value, popularity_score,
                is_land, is_creature, asset_age_years, rarity_score, target_return_7d_pct
            FROM fact_training_dataset
            WHERE target_return_7d_pct IS NOT NULL
              AND current_price >= 2.50
              AND target_return_7d_pct BETWEEN -50.0 AND 150.0
        """
        df = conn.execute(query).fetchdf()
        conn.close()

    df['price_date'] = pd.to_datetime(df['price_date'])
    df = df.sort_values('price_date').reset_index(drop=True)
    
    feature_cols = [
        'sma_ratio', 'volatility_14d', 'daily_return_pct', 'velocity_7d_pct',
        'bid_ask_spread_pct', 'spread_velocity_7d', 'vendor_delta_7d',
        'price_decay_velocity_3d', 'amihud_illiquidity_30d',
        'is_foil', 'is_reserved', 'mana_value', 'popularity_score',
        'is_land', 'is_creature', 'asset_age_years', 'rarity_score'
    ]
    target_col = 'target_return_7d_pct'
    
    df[feature_cols] = df[feature_cols].fillna(0.0)
    
    total_days = (df['price_date'].max() - df['price_date'].min()).days
    EMBARGO_DAYS = 14
    test_days = max(5, int(total_days * 0.15))
    val_days = max(5, int(total_days * 0.15))
    
    test_start_date = df['price_date'].max() - pd.Timedelta(days=test_days)
    val_end_date = test_start_date - pd.Timedelta(days=EMBARGO_DAYS)
    val_start_date = val_end_date - pd.Timedelta(days=val_days)
    
    train_cutoff_date = val_start_date - pd.Timedelta(days=EMBARGO_DAYS)
    cal_cutoff_date = train_cutoff_date - pd.Timedelta(days=val_days)
    
    X = df[feature_cols]
    y = df[target_col]
    
    train_mask = df['price_date'] <= cal_cutoff_date
    cal_mask = (df['price_date'] > cal_cutoff_date) & (df['price_date'] <= train_cutoff_date)
    val_mask = (df['price_date'] >= val_start_date) & (df['price_date'] <= val_end_date)
    test_mask = df['price_date'] >= test_start_date
    
    X_train, y_train = X.loc[train_mask], y.loc[train_mask]
    X_cal, y_cal = X.loc[cal_mask], y.loc[cal_mask]
    X_val, y_val = X.loc[val_mask], y.loc[val_mask]
    X_test, y_test = X.loc[test_mask], y.loc[test_mask]
    
    HURDLE_UPWARD_PCT = 12.0
    y_train_class = (y_train >= HURDLE_UPWARD_PCT).astype(int)
    y_val_class = (y_val >= HURDLE_UPWARD_PCT).astype(int)
    
    pos_count = int(y_train_class.sum())
    neg_count = len(y_train_class) - pos_count
    scale_weight = (neg_count / pos_count) if pos_count > 0 else 1.0

    splits_summary = {
        "Train Set": {
            "range": f"{df.loc[train_mask, 'price_date'].min().strftime('%Y-%m-%d')} → {cal_cutoff_date.strftime('%Y-%m-%d')}",
            "count": len(X_train),
            "movers": int(y_train_class.sum()),
            "movers_pct": (y_train_class.sum() / len(y_train_class) * 100) if len(y_train_class) else 0.0,
            "is_embargo": False
        },
        "Calibration Set": {
            "range": f"{(cal_cutoff_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')} → {train_cutoff_date.strftime('%Y-%m-%d')}",
            "count": len(X_cal),
            "movers": int((y_cal >= HURDLE_UPWARD_PCT).sum()),
            "movers_pct": ((y_cal >= HURDLE_UPWARD_PCT).sum() / len(y_cal) * 100) if len(y_cal) else 0.0,
            "is_embargo": False
        },
        "Embargo Gap 1": {
            "range": f"{(train_cutoff_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')} → {(val_start_date - pd.Timedelta(days=1)).strftime('%Y-%m-%d')} ({EMBARGO_DAYS}d)",
            "is_embargo": True
        },
        "Validation Set": {
            "range": f"{val_start_date.strftime('%Y-%m-%d')} → {val_end_date.strftime('%Y-%m-%d')}",
            "count": len(X_val),
            "movers": int(y_val_class.sum()),
            "movers_pct": (y_val_class.sum() / len(y_val_class) * 100) if len(y_val_class) else 0.0,
            "is_embargo": False
        },
        "Embargo Gap 2": {
            "range": f"{(val_end_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')} → {(test_start_date - pd.Timedelta(days=1)).strftime('%Y-%m-%d')} ({EMBARGO_DAYS}d)",
            "is_embargo": True
        },
        "Test Set (Holdout)": {
            "range": f"{test_start_date.strftime('%Y-%m-%d')} → {df['price_date'].max().strftime('%Y-%m-%d')}",
            "count": len(X_test),
            "movers": int((y_test >= HURDLE_UPWARD_PCT).sum()),
            "movers_pct": ((y_test >= HURDLE_UPWARD_PCT).sum() / len(y_test) * 100) if len(y_test) else 0.0,
            "is_embargo": False
        },
    }
    
    print_split_table(splits_summary, len(df))

    with Progress(
        SpinnerColumn(spinner_name="dots", style="bold cyan"),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=35, style="dim white", complete_style="bold cyan"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False
    ) as progress:
        
        task = progress.add_task("[cyan]Executing Training Steps...", total=6)
        
        progress.update(task, description="[bold cyan][1/6] Training XGBClassifier (Spike Hurdle Engine)...")
        classifier = XGBClassifier(
            n_estimators=300, learning_rate=0.04, max_depth=6, gamma=0.5,
            subsample=0.85, colsample_bytree=0.80, scale_pos_weight=scale_weight,
            tree_method='hist', random_state=42, n_jobs=4, eval_metric='logloss'
        )
        classifier.fit(X_train, y_train_class)
        progress.advance(task)
        
        progress.update(task, description="[bold cyan][2/6] Training SAEHL XGBRegressor on Movers...")
        movers_mask = y_train_class == 1
        X_train_movers, y_train_movers = X_train.loc[movers_mask], y_train.loc[movers_mask]
        
        regressor = XGBRegressor(
            n_estimators=300, learning_rate=0.03, max_depth=5, gamma=0.5,
            subsample=0.85, colsample_bytree=0.80, tree_method='hist',
            random_state=42, n_jobs=4, objective=smooth_asymmetric_huber_objective
        )
        regressor.fit(X_train_movers if len(X_train_movers) > 0 else X_train,
                      y_train_movers if len(X_train_movers) > 0 else y_train)
        progress.advance(task)
        
        progress.update(task, description="[bold cyan][3/6] Fitting & Calibrating Conformal Lower Bounds (CQR)...")
        cqr_generator = ConformalizedLowerBoundGenerator(alpha=0.10)
        cqr_generator.fit_and_calibrate(X_train, y_train, X_cal, y_cal)
        progress.advance(task)
        
        progress.update(task, description="[bold cyan][4/6] Optimizing Hurdle Decision Thresholds (MAE Sweep)...")
        raw_val_probs = classifier.predict_proba(X_val)[:, 1]
        raw_val_mags = regressor.predict(X_val)
        y_val_arr = y_val.to_numpy()
        best_mae, best_prob_thresh = float('inf'), 0.95
        
        for candidate in np.linspace(0.50, 0.98, 49):
            filtered_preds = np.where(raw_val_probs >= candidate, raw_val_mags, 0.0)
            candidate_mae = mean_absolute_error(y_val_arr, filtered_preds)
            if candidate_mae < best_mae:
                best_mae = candidate_mae
                best_prob_thresh = float(candidate)
        progress.advance(task)
        
        progress.update(task, description="[bold cyan][5/6] Profiling Ensemble Trajectory & Epistemic Variance...")
        tree_preds = []
        for i in range(regressor.n_estimators):
            tree_preds.append(regressor.predict(X_val, iteration_range=(0, i + 1)))
        epistemic_variance_val = float(np.var(tree_preds, axis=0).mean())
        progress.advance(task)
        
        progress.update(task, description="[bold cyan][6/6] Serializing Model Bundles & Exporting Metadata...")
        os.makedirs(model_output_dir, exist_ok=True)
        model_path = os.path.join(model_output_dir, "xgboost_forecast.joblib")
        
        metrics_payload = {
            "prob_threshold": float(best_prob_thresh),
            "epistemic_var_baseline": float(epistemic_variance_val),
            "split_date": str(test_start_date.date()),
            "hurdle_upward_pct": float(HURDLE_UPWARD_PCT)
        }
        
        joblib.dump({
            "classifier": classifier,
            "regressor": regressor,
            "cqr_generator": cqr_generator,
            "feature_cols": feature_cols,
            "metrics": metrics_payload
        }, model_path)
        progress.advance(task)
        
    console.print()
    print_post_training_report(
        metrics_payload, classifier, regressor, feature_cols,
        X_val, y_val, X_test, y_test, cqr_generator
    )
    
    file_size_mb = os.path.getsize(model_path) / (1024 * 1024)
    duration = time.time() - start_time
    
    summary_text = Text()
    summary_text.append("✔ Training pipeline completed successfully!\n", style="bold green")
    summary_text.append(f"• Model Path: {model_path} ({file_size_mb:.2f} MB)\n", style="white")
    summary_text.append(f"• Total Elapsed Time: {duration:.2f}s  |  Status: Ready for Production Inference", style="dim")
    
    console.print(Panel(summary_text, border_style="green", box=box.ROUNDED))

if __name__ == "__main__":
    train_xgboost_forecast(str(DB_PATH), str(MODEL_DIR))