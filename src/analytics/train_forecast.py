import os
import sys
from pathlib import Path
import duckdb
import pandas as pd
import numpy as np
import joblib
from xgboost import XGBRegressor, XGBClassifier
from sklearn.metrics import mean_absolute_error, mean_squared_error

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"
MODEL_DIR = BASE_DIR / "models"


def train_xgboost_forecast(db_path: str, model_output_dir: str):
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

    print(f"Train split : <= {train_cutoff_date.date()} ({len(X_train):,} rows)")
    print(f"Val split   : {val_start_date.date()} to {val_end_date.date()} ({len(X_val):,} rows, 14d embargo)")
    print(f"Test split  : >= {test_start_date.date()} ({len(X_test):,} rows, 14d embargo)")

    if len(X_train) == 0 or len(X_val) == 0 or len(X_test) == 0:
        raise ValueError("Empty split encountered. Check date distributions in fact_training_dataset.")

    # 3. Model Training with Hist Tree Method and bounded threads
    HURDLE_PCT = 4.50
    y_train_class = (np.abs(y_train) >= HURDLE_PCT).astype(int)
    y_val_class = (np.abs(y_val) >= HURDLE_PCT).astype(int)
    y_test_class = (np.abs(y_test) >= HURDLE_PCT).astype(int)

    pos_count = int(y_train_class.sum())
    neg_count = len(y_train_class) - pos_count
    scale_weight = (neg_count / pos_count) if pos_count > 0 else 1.0

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

    # 4. Calibrate confidence threshold tau strictly on validation set
    print("Calibrating decision threshold on validation set...")
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

    if best_prob_thresh <= 1.0:
        print(f"Optimal threshold locked: tau = {best_prob_thresh:.2f} (Val MAE: {best_mae:.4f}%)")
    else:
        print("Warning: Model did not beat naive 0.0% baseline on validation set. Falling back to zero-return mode.")

    # 5. Evaluate on out-of-time blind test set
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

    print("\n--- Out-of-Time Test Set Evaluation ---")
    print(f"Optimal threshold (tau)  : {best_prob_thresh:.2f}")
    print(f"Model MAE                : {mae:.4f}%")
    print(f"Naive Baseline MAE       : {naive_mae:.4f}%")
    print(f"Model RMSE               : {rmse:.4f}%")
    print(f"Triggered Signals        : {total_active_trades:,} / {len(X_test):,} ({total_active_trades / len(X_test) * 100:.2f}%)")
    print(f"Directional Accuracy     : {directional_accuracy:.2f}% (on triggered signals)")

    if mae < naive_mae:
        edge_bps = (naive_mae - mae) * 100
        print(f"Model beat naive baseline by {edge_bps:.1f} bps.")
    else:
        print("Quality gate warning: Model MAE did not beat naive zero-return baseline.")

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
    print(f"Saved artifact to: {model_path}\n")


if __name__ == "__main__":
    train_xgboost_forecast(str(DB_PATH), str(MODEL_DIR))