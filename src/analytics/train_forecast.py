import os
import sys
from pathlib import Path
import duckdb
import pandas as pd
import numpy as np
import joblib
from xgboost import XGBRegressor, XGBClassifier
from sklearn.metrics import mean_absolute_error, mean_squared_error

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"
MODEL_DIR = BASE_DIR / "models"


def train_xgboost_forecast(db_path: str, model_output_dir: str):
    if HAS_RICH:
        console.print(Panel(
            "[bold white]XGBoost Two-Stage Price Forecasting Pipeline[/bold white]\n"
            f"[dim]Training Store: {db_path}[/dim]",
            box=box.ROUNDED,
            border_style="cyan"
        ))
    else:
        print(f"Training two-stage forecast model against: {db_path}")

    if not Path(db_path).exists():
        raise FileNotFoundError(f"Database not found at '{db_path}'. Run ETL & feature pipeline first.")

    # 1. Load dataset (filter bulk penny cards <$2.50 to avoid zero-inflation noise)
    conn = duckdb.connect(db_path, read_only=True, config={
        'max_memory': '2GB',
        'threads': '4'
    })
    query = """
        SELECT
            price_date,
            sma_ratio,
            volatility_14d,
            daily_return_pct,
            velocity_7d_pct,
            bid_ask_spread_pct,
            spread_velocity_7d,
            vendor_delta_7d,
            is_foil,
            is_reserved,
            mana_value,
            popularity_score,
            is_land,
            is_creature,
            asset_age_years,
            rarity_score,
            target_return_7d_pct
        FROM fact_training_dataset
        WHERE target_return_7d_pct IS NOT NULL
          AND current_price >= 2.50
          AND target_return_7d_pct BETWEEN -50.0 AND 150.0
    """
    df = conn.execute(query).fetchdf()
    conn.close()

    if len(df) == 0:
        raise ValueError("Training dataset is empty. Check fact_training_dataset in DuckDB.")

    if HAS_RICH:
        console.print(f"[bold cyan]→ Loaded dataset:[/bold cyan] [bold white]{len(df):,}[/bold white] training instances\n")
    else:
        print(f"Loaded {len(df):,} training instances.")

    # 2. Chronological split with 14-day anti-leakage embargoes
    df['price_date'] = pd.to_datetime(df['price_date'])
    df = df.sort_values('price_date').reset_index(drop=True)
    feature_cols = [
        'sma_ratio', 'volatility_14d', 'daily_return_pct', 'velocity_7d_pct',
        'bid_ask_spread_pct', 'spread_velocity_7d', 'vendor_delta_7d',
        'is_foil', 'is_reserved', 'mana_value', 'popularity_score',
        'is_land', 'is_creature', 'asset_age_years', 'rarity_score'
    ]
    target_col = 'target_return_7d_pct'
    fill_defaults = {
        'sma_ratio': 1.0,
        'volatility_14d': 0.0,
        'daily_return_pct': 0.0,
        'velocity_7d_pct': 0.0,
        'bid_ask_spread_pct': 1.0,
        'spread_velocity_7d': 0.0,
        'vendor_delta_7d': 0.0,
        'is_foil': 0,
        'is_reserved': 0,
        'mana_value': 0.0,
        'popularity_score': 0.0,
        'is_land': 0,
        'is_creature': 0,
        'asset_age_years': 0.0,
        'rarity_score': 1
    }
    df[feature_cols] = df[feature_cols].fillna(value=fill_defaults)

    min_date = df['price_date'].min()
    max_date = df['price_date'].max()
    total_days = (max_date - min_date).days
    EMBARGO_DAYS = 14
    if total_days < (EMBARGO_DAYS * 2 + 10):
        raise ValueError(
            f"Insufficient date range ({total_days} days). Need at least {EMBARGO_DAYS * 2 + 10} days for embargoes."
        )

    test_days = max(5, int(total_days * 0.15))
    val_days = max(5, int(total_days * 0.15))

    test_start_date = max_date - pd.Timedelta(days=test_days)
    val_end_date = test_start_date - pd.Timedelta(days=EMBARGO_DAYS)
    val_start_date = val_end_date - pd.Timedelta(days=val_days)
    train_cutoff_date = val_start_date - pd.Timedelta(days=EMBARGO_DAYS)

    if train_cutoff_date <= min_date:
        remaining_days = max(1, total_days - (2 * EMBARGO_DAYS))
        train_days = int(remaining_days * 0.60)
        val_days = int(remaining_days * 0.20)
        train_cutoff_date = min_date + pd.Timedelta(days=train_days)
        val_start_date = train_cutoff_date + pd.Timedelta(days=EMBARGO_DAYS)
        val_end_date = val_start_date + pd.Timedelta(days=val_days)
        test_start_date = val_end_date + pd.Timedelta(days=EMBARGO_DAYS)

    X = df[feature_cols]
    y = df[target_col]

    train_mask = df['price_date'] <= train_cutoff_date
    val_mask = (df['price_date'] >= val_start_date) & (df['price_date'] <= val_end_date)
    test_mask = df['price_date'] >= test_start_date

    X_train, y_train = X.loc[train_mask], y.loc[train_mask]
    X_val, y_val = X.loc[val_mask], y.loc[val_mask]
    X_test, y_test = X.loc[test_mask], y.loc[test_mask]

    if HAS_RICH:
        split_table = Table(
            title="[bold white]TEMPORAL ANTI-LEAKAGE EMBARGO PARTITIONS[/bold white]",
            box=box.ROUNDED,
            border_style="bright_black",
            show_header=True,
            header_style="bold cyan"
        )
        split_table.add_column("Partition", style="bold white")
        split_table.add_column("Date Range", style="dim")
        split_table.add_column("Rows", justify="right", style="cyan")
        split_table.add_column("Embargo Guard", justify="center", style="bold green")
        split_table.add_row("Training", f"<= {train_cutoff_date.date()}", f"{len(X_train):,}", "Primary")
        split_table.add_row("Validation", f"{val_start_date.date()} → {val_end_date.date()}", f"{len(X_val):,}", "14d Anti-Leakage")
        split_table.add_row("Out-Of-Time Test", f">= {test_start_date.date()}", f"{len(X_test):,}", "14d Anti-Leakage")
        console.print(split_table)
        console.print()
    else:
        print(f"Train split : <= {train_cutoff_date.date()} ({len(X_train):,} rows)")
        print(f"Val split   : {val_start_date.date()} to {val_end_date.date()} ({len(X_val):,} rows, 14d embargo)")
        print(f"Test split  : >= {test_start_date.date()} ({len(X_test):,} rows, 14d embargo)")

    if len(X_train) == 0 or len(X_val) == 0 or len(X_test) == 0:
        raise ValueError("Empty split encountered. Check date distributions in fact_training_dataset.")

    # 3. Model Training
    HURDLE_PCT = 4.50
    y_train_class = (np.abs(y_train) >= HURDLE_PCT).astype(int)
    y_val_class = (np.abs(y_val) >= HURDLE_PCT).astype(int)
    y_test_class = (np.abs(y_test) >= HURDLE_PCT).astype(int)

    pos_count = int(y_train_class.sum())
    neg_count = len(y_train_class) - pos_count
    scale_weight = (neg_count / pos_count) if pos_count > 0 else 1.0

    if HAS_RICH:
        with console.status("[bold cyan]Fitting Stage 1 Classifier (Breakout Mover Detection)...[/bold cyan]"):
            classifier = XGBClassifier(
                n_estimators=300,
                learning_rate=0.04,
                max_depth=6,
                gamma=0.5,
                subsample=0.85,
                colsample_bytree=0.80,
                scale_pos_weight=scale_weight,
                tree_method='hist',
                random_state=42,
                n_jobs=4,
                eval_metric='logloss'
            )
            classifier.fit(X_train, y_train_class)
        console.print("  [bold green]✓ Stage 1 Fitted:[/bold green] XGBClassifier (scale_pos_weight: {:.2f})".format(scale_weight))

        with console.status("[bold cyan]Fitting Stage 2 Regressor (Magnitude Conditional on Breakout)...[/bold cyan]"):
            movers_mask = y_train_class == 1
            X_train_movers = X_train.loc[movers_mask]
            y_train_movers = y_train.loc[movers_mask]
            regressor = XGBRegressor(
                n_estimators=300,
                learning_rate=0.03,
                max_depth=5,
                gamma=0.5,
                subsample=0.85,
                colsample_bytree=0.80,
                reg_alpha=2.0,
                reg_lambda=2.0,
                tree_method='hist',
                random_state=42,
                n_jobs=4,
                objective='reg:absoluteerror'
            )
            if len(X_train_movers) > 0:
                regressor.fit(X_train_movers, y_train_movers)
            else:
                regressor.fit(X_train, y_train)
        console.print("  [bold green]✓ Stage 2 Fitted:[/bold green] XGBRegressor (Objective: reg:absoluteerror)\n")
    else:
        print("Fitting Stage 1 classifier (mover detection)...")
        classifier = XGBClassifier(
            n_estimators=300,
            learning_rate=0.04,
            max_depth=6,
            gamma=0.5,
            subsample=0.85,
            colsample_bytree=0.80,
            scale_pos_weight=scale_weight,
            tree_method='hist',
            random_state=42,
            n_jobs=4,
            eval_metric='logloss'
        )
        classifier.fit(X_train, y_train_class)
        print("Fitting Stage 2 regressor (magnitude conditional on mover)...")
        movers_mask = y_train_class == 1
        X_train_movers = X_train.loc[movers_mask]
        y_train_movers = y_train.loc[movers_mask]
        regressor = XGBRegressor(
            n_estimators=300,
            learning_rate=0.03,
            max_depth=5,
            gamma=0.5,
            subsample=0.85,
            colsample_bytree=0.80,
            reg_alpha=2.0,
            reg_lambda=2.0,
            tree_method='hist',
            random_state=42,
            n_jobs=4,
            objective='reg:absoluteerror'
        )
        if len(X_train_movers) > 0:
            regressor.fit(X_train_movers, y_train_movers)
        else:
            regressor.fit(X_train, y_train)

    # 4. Calibrate confidence threshold tau on validation set
    raw_val_probs = classifier.predict_proba(X_val)[:, 1]
    raw_val_mags = regressor.predict(X_val)
    y_val_arr = y_val.to_numpy()
    naive_val_mae = mean_absolute_error(y_val_arr, np.zeros_like(y_val_arr))
    best_mae = naive_val_mae
    best_prob_thresh = 1.01

    for candidate in np.linspace(0.10, 0.95, 86):
        filtered_preds = np.where(raw_val_probs >= candidate, raw_val_mags, 0.0)
        candidate_mae = mean_absolute_error(y_val_arr, filtered_preds)
        if candidate_mae < best_mae:
            best_mae = candidate_mae
            best_prob_thresh = candidate

    # 5. Evaluate on blind test set
    test_probs = classifier.predict_proba(X_test)[:, 1]
    test_mags = regressor.predict(X_test)
    y_test_arr = y_test.to_numpy()
    naive_predictions = np.zeros_like(y_test_arr)
    naive_mae = mean_absolute_error(y_test_arr, naive_predictions)

    if best_prob_thresh <= 1.0:
        predictions = np.where(test_probs >= best_prob_thresh, test_mags, 0.0)
    else:
        predictions = np.zeros_like(y_test_arr)

    mae = mean_absolute_error(y_test_arr, predictions)
    rmse = np.sqrt(mean_squared_error(y_test_arr, predictions))
    active_mask = predictions != 0.0
    total_active_trades = int(active_mask.sum())
    if total_active_trades > 0:
        actual_signs = np.sign(y_test_arr[active_mask])
        pred_signs = np.sign(predictions[active_mask])
        correct_trades = (actual_signs == pred_signs) & (y_test_arr[active_mask] != 0.0)
        directional_accuracy = float(correct_trades.mean() * 100.0)
    else:
        directional_accuracy = 0.0

    if HAS_RICH:
        score_table = Table(
            title="[bold white]OUT-OF-TIME BLIND TEST SET EVALUATION[/bold white]",
            box=box.ROUNDED,
            border_style="bright_black",
            show_header=True,
            header_style="bold cyan",
            expand=True
        )
        score_table.add_column("Optimal Cutoff (τ)", justify="center")
        score_table.add_column("Model MAE", justify="center", style="bold green")
        score_table.add_column("Naive Zero-MAE", justify="center", style="dim yellow")
        score_table.add_column("Model RMSE", justify="center")
        score_table.add_column("Signals Triggered", justify="center")
        score_table.add_column("Directional Accuracy", justify="center", style="bold green")

        score_table.add_row(
            f"τ = {best_prob_thresh:.2f}",
            f"{mae:.4f}%",
            f"{naive_mae:.4f}%",
            f"{rmse:.4f}%",
            f"{total_active_trades:,} / {len(X_test):,} ({total_active_trades / len(X_test) * 100:.1f}%)",
            f"{directional_accuracy:.1f}%"
        )
        console.print(score_table)
        console.print()
    else:
        print("\n--- Out-of-Time Test Set Evaluation ---")
        print(f"Optimal threshold (tau)  : {best_prob_thresh:.2f}")
        print(f"Model MAE                : {mae:.4f}%")
        print(f"Naive Baseline MAE       : {naive_mae:.4f}%")
        print(f"Model RMSE               : {rmse:.4f}%")
        print(f"Triggered Signals        : {total_active_trades:,} / {len(X_test):,} ({total_active_trades / len(X_test) * 100:.2f}%)")
        print(f"Directional Accuracy     : {directional_accuracy:.2f}% (on triggered signals)")

    # 6. Save model artifact
    os.makedirs(model_output_dir, exist_ok=True)
    model_path = os.path.join(model_output_dir, "xgboost_forecast.joblib")
    artifact = {
        "classifier": classifier,
        "regressor": regressor,
        "feature_cols": feature_cols,
        "target_col": target_col,
        "metrics": {
            "mae_pct": round(float(mae), 4),
            "naive_mae_pct": round(float(naive_mae), 4),
            "rmse_pct": round(float(rmse), 4),
            "directional_accuracy_pct": round(float(directional_accuracy), 2),
            "prob_threshold": round(float(best_prob_thresh), 4),
            "hurdle_pct": float(HURDLE_PCT),
            "split_date": str(test_start_date.date())
        }
    }
    joblib.dump(artifact, model_path)

    if HAS_RICH:
        console.print(f"[bold green]✓ Model artifact successfully serialized:[/bold green] [white]{model_path}[/white]\n")
    else:
        print(f"Saved artifact to: {model_path}\n")


if __name__ == "__main__":
    train_xgboost_forecast(str(DB_PATH), str(MODEL_DIR))