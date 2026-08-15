import os
from pathlib import Path
import duckdb
import pandas as pd
import numpy as np
import joblib
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error


def train_xgboost_forecast(db_path: str, model_output_dir: str):
    print("Loading ML dataset from DuckDB...")
    conn = duckdb.connect(db_path, read_only=True)
    
    # Query features and stationary relative percentage target
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
          AND current_price > 0.05
          -- Filter extreme market anomalies/feed spikes
          AND target_return_7d_pct BETWEEN -90.0 AND 300.0
    """
    df = conn.execute(query).fetchdf()
    conn.close()
    
    if len(df) == 0:
        raise ValueError("No training rows found. Ensure ETL and build_features scripts have been executed.")

    print(f"Loaded {len(df):,} sanitized historical samples.")

    # --------------------------------------------------------------------------
    # 1. TEMPORAL SORT & OUT-OF-TIME CHRONOLOGICAL SPLIT WITH EMBARGO
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
    
    X = df[feature_cols].fillna(0.0)
    y = df[target_col]

    # Chronological 80/20 train/test cutoff
    split_idx = int(len(df) * 0.8)
    initial_cutoff_date = df.loc[split_idx, 'price_date']
    
    # 7-day embargo to prevent target lookahead leakage into the test set
    test_start_date = initial_cutoff_date + pd.Timedelta(days=7)
    
    train_mask = df['price_date'] <= initial_cutoff_date
    test_mask = df['price_date'] >= test_start_date
    
    X_train, y_train = X.loc[train_mask], y.loc[train_mask]
    X_test, y_test = X.loc[test_mask], y.loc[test_mask]

    print(f"Training Cutoff: {initial_cutoff_date.date()} | Test Start: {test_start_date.date()}")
    print(f"Training set: {len(X_train):,} rows | Test set: {len(X_test):,} rows")

    # --------------------------------------------------------------------------
    # 2. MODEL TRAINING (Regularized Gradient Boosting)
    # --------------------------------------------------------------------------
    print("Training XGBoost Regressor on asset return momentum...")
    model = XGBRegressor(
        n_estimators=180,
        learning_rate=0.03,
        max_depth=5,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=-1
    )
    
    model.fit(X_train, y_train)

    # --------------------------------------------------------------------------
    # 3. QUANTITATIVE EVALUATION & BASELINE COMPARISON
    # --------------------------------------------------------------------------
    predictions = model.predict(X_test)
    mae = mean_absolute_error(y_test, predictions)
    rmse = np.sqrt(mean_squared_error(y_test, predictions))

    # Naive baseline: Assume 0% change over 7 days
    naive_predictions = np.zeros_like(y_test)
    naive_mae = mean_absolute_error(y_test, naive_predictions)
    
    # Filter out perfectly flat historical returns to prevent accuracy inflation
    movement_mask = y_test != 0
    y_test_moves = y_test[movement_mask]
    pred_moves = predictions[movement_mask]
    
    if len(y_test_moves) > 0:
        actual_direction = (y_test_moves > 0).astype(int)
        predicted_direction = (pred_moves > 0).astype(int)
        directional_accuracy = (actual_direction == predicted_direction).mean() * 100.0
    else:
        directional_accuracy = 0.0

    print("\n--- Model Evaluation Results (Out-of-Time Test Set) ---")
    print(f"Model Mean Absolute Error (MAE):    {mae:.2f}% return variance")
    print(f"Naive Zero-Return Baseline MAE:     {naive_mae:.2f}% return variance")
    print(f"Root Mean Squared Error (RMSE):     {rmse:.2f}%")
    print(f"Directional Sign Accuracy:          {directional_accuracy:.1f}%")

    # --------------------------------------------------------------------------
    # 4. ARTIFACT PERSISTENCE
    # --------------------------------------------------------------------------
    os.makedirs(model_output_dir, exist_ok=True)
    model_path = os.path.join(model_output_dir, "xgboost_forecast.joblib")
    
    artifact = {
        "model": model,
        "feature_cols": feature_cols,
        "target_col": target_col,
        "metrics": {
            "mae_pct": round(float(mae), 4), 
            "rmse_pct": round(float(rmse), 4),
            "directional_accuracy_pct": round(float(directional_accuracy), 2),
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