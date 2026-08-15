import os
import sys
from pathlib import Path
import duckdb
import pandas as pd
import numpy as np
import joblib
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error


# Quant conviction threshold: price drift < 0.50% is unactionable market noise
DEADBAND_THRESHOLD_PCT = 0.50


def train_xgboost_forecast(db_path: str, model_output_dir: str):
    print("Loading ML dataset from DuckDB...")
    conn = duckdb.connect(db_path, read_only=True)
    
    query = """
        SELECT 
            price_date,
            sma_ratio,
            volatility_14d,
            daily_return_pct,
            velocity_7d_pct,
            is_foil,
            rarity_score,
            edhrec_rank,
            target_return_7d_pct
        FROM fact_training_dataset
        WHERE target_return_7d_pct IS NOT NULL 
          AND current_price >= 2.50
          AND target_return_7d_pct BETWEEN -50.0 AND 150.0
    """
    df = conn.execute(query).fetchdf()
    conn.close()
    
    if len(df) == 0:
        raise ValueError("No training rows found. Ensure ETL and build_features scripts have been executed.")

    print(f"Loaded {len(df):,} sanitized historical samples.")

    # --------------------------------------------------------------------------
    # 1. Temporal Sort & Chronological Split with 8-Day Embargo
    # --------------------------------------------------------------------------
    df['price_date'] = pd.to_datetime(df['price_date'])
    df = df.sort_values('price_date').reset_index(drop=True)

    feature_cols = [
        'sma_ratio', 
        'volatility_14d', 
        'daily_return_pct', 
        'velocity_7d_pct',
        'is_foil',
        'rarity_score',
        'edhrec_rank'
    ]
    target_col = 'target_return_7d_pct'
    
    if 'sma_ratio' in df.columns:
        df['sma_ratio'] = df['sma_ratio'].fillna(1.0)
    
    X = df[feature_cols]
    y = df[target_col]

    split_idx = int(len(df) * 0.8)
    initial_cutoff_date = df.loc[split_idx, 'price_date']
    
    # 8-day embargo guarantees no 7-day target overlaps test feature dates
    test_start_date = initial_cutoff_date + pd.Timedelta(days=8)
    
    train_mask = df['price_date'] <= initial_cutoff_date
    test_mask = df['price_date'] >= test_start_date
    
    X_train, y_train = X.loc[train_mask], y.loc[train_mask]
    X_test, y_test = X.loc[test_mask], y.loc[test_mask]

    print(f"Training Cutoff: {initial_cutoff_date.date()} | Test Start: {test_start_date.date()}")
    print(f"Training set: {len(X_train):,} rows | Test set: {len(X_test):,} rows")

    # --------------------------------------------------------------------------
    # 2. Model Training (Optimized for L1 Loss + Interaction Capacity)
    # --------------------------------------------------------------------------
    print("Training XGBoost Regressor on asset return momentum...")
    model = XGBRegressor(
        n_estimators=200,
        learning_rate=0.04,
        max_depth=6,
        gamma=0.5,             # Minimum loss reduction required to make a further partition
        subsample=0.85,
        colsample_bytree=0.85,
        reg_alpha=4.0,         # L1 Regularization for leaf sparsity
        reg_lambda=2.0,        # L2 Regularization
        random_state=42,
        n_jobs=-1,
        objective='reg:absoluteerror'
    )
    
    model.fit(X_train, y_train)

    # --------------------------------------------------------------------------
    # 3. Quantitative Evaluation with Signal Deadband
    # --------------------------------------------------------------------------
    raw_predictions = model.predict(X_test)
    
    # Apply conviction filter (deadband): zero out noise below threshold
    predictions = np.where(np.abs(raw_predictions) < DEADBAND_THRESHOLD_PCT, 0.0, raw_predictions)
    
    mae = mean_absolute_error(y_test, predictions)
    rmse = np.sqrt(mean_squared_error(y_test, predictions))

    # Naive baseline: Assume 0% change over 7 days
    naive_predictions = np.zeros_like(y_test)
    naive_mae = mean_absolute_error(y_test, naive_predictions)
    
    movement_mask = y_test != 0
    y_test_moves = y_test[movement_mask]
    pred_moves = predictions[movement_mask]
    
    if len(y_test_moves) > 0:
        actual_direction = np.sign(y_test_moves)
        predicted_direction = np.sign(pred_moves)
        directional_accuracy = (actual_direction == predicted_direction).mean() * 100.0
    else:
        directional_accuracy = 0.0

    print("\n--- Model Evaluation Results (Out-of-Time Test Set) ---")
    print(f"Model Mean Absolute Error (MAE):    {mae:.2f}% return variance")
    print(f"Naive Zero-Return Baseline MAE:     {naive_mae:.2f}% return variance")
    print(f"Root Mean Squared Error (RMSE):     {rmse:.2f}%")
    print(f"Directional Sign Accuracy:          {directional_accuracy:.1f}%")

    # --------------------------------------------------------------------------
    # 4. Quality Gate & Artifact Persistence
    # --------------------------------------------------------------------------
    if mae > naive_mae:
        print(f"\n⚠️  [Quality Alert] Model MAE ({mae:.2f}%) did not outperform Naive Baseline ({naive_mae:.2f}%).")
        print("    Persisting artifact with performance diagnostics logged.")
    else:
        print(f"\n✅ [Quality Gate Passed] Model MAE ({mae:.2f}%) outperformed Naive Baseline ({naive_mae:.2f}%).")

    os.makedirs(model_output_dir, exist_ok=True)
    model_path = os.path.join(model_output_dir, "xgboost_forecast.joblib")
    
    artifact = {
        "model": model,
        "feature_cols": feature_cols,
        "target_col": target_col,
        "metrics": {
            "mae_pct": round(float(mae), 4),
            "naive_mae_pct": round(float(naive_mae), 4),
            "rmse_pct": round(float(rmse), 4),
            "directional_accuracy_pct": round(float(directional_accuracy), 2),
            "deadband_threshold_pct": DEADBAND_THRESHOLD_PCT,
            "split_date": str(initial_cutoff_date.date())
        }
    }
    
    joblib.dump(artifact, model_path)
    print(f"\nModel artifact successfully saved to: {model_path}")


if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parent.parent.parent
    DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"
    MODEL_DIR = BASE_DIR / "models"
    
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}. Run ETL & feature engineering first.")
    else:
        train_xgboost_forecast(str(DB_PATH), str(MODEL_DIR))