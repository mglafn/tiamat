import os
import duckdb
import pandas as pd
import numpy as np
import joblib
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

def train_xgboost_forecast(db_path, model_output_dir):
    print("Loading ML training dataset from DuckDB...")
    conn = duckdb.connect(db_path, read_only=True)
    
    # Query complete dataset where target exists (drops recent 7 days lacking target)
    query = """
        SELECT 
            price_date,
            current_price,
            sma_7,
            sma_30,
            daily_return_pct,
            target_price_7d
        FROM fact_training_dataset
        WHERE target_price_7d IS NOT NULL AND current_price > 0
        ORDER BY price_date ASC
    """
    df = conn.execute(query).fetchdf()
    conn.close()

    print(f"Loaded {len(df):,} historical price points for ML training.")

    # Define features and target
    feature_cols = ['current_price', 'sma_7', 'sma_30', 'daily_return_pct']
    target_col = 'target_price_7d'

    X = df[feature_cols]
    y = df[target_col]

    # Time-Series Train/Test Split (80% Train, 20% Out-of-time Test)
    split_idx = int(len(df) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    print(f"Training set: {len(X_train):,} rows | Test set: {len(X_test):,} rows")

    # Train XGBoost Model
    print("Training XGBoost Regressor model...")
    model = XGBRegressor(
        n_estimators=150,
        learning_rate=0.03,
        max_depth=6,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1
    )
    model.fit(X_train, y_train)

    # Evaluation
    predictions = model.predict(X_test)
    mae = mean_absolute_error(y_test, predictions)
    rmse = np.sqrt(mean_squared_error(y_test, predictions))

    print("\n--- Model Evaluation Results ---")
    print(f"Mean Absolute Error (MAE): ${mae:.4f}")
    print(f"Root Mean Squared Error (RMSE): ${rmse:.4f}")

    # Persist Artifacts
    os.makedirs(model_output_dir, exist_ok=True)
    model_path = os.path.join(model_output_dir, "xgboost_forecast.joblib")
    
    artifact = {
        "model": model,
        "feature_cols": feature_cols,
        "metrics": {"mae": mae, "rmse": rmse}
    }
    joblib.dump(artifact, model_path)
    print(f"Model successfully saved to: {model_path}")

if __name__ == "__main__":
    db_path = os.path.join("data", "mtg_prices.duckdb")
    model_dir = os.path.join("models")
    train_xgboost_forecast(db_path, model_dir)