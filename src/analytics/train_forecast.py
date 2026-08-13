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
    """
    df = conn.execute(query).fetchdf()
    conn.close()
    
    print(f"Loaded {len(df):,} historical price points.")

    # --------------------------------------------------------------------------
    # DATA PRE-PROCESSING & TEMPORAL SPLIT
    # --------------------------------------------------------------------------
    # Ensure date is a datetime object and sorted correctly
    df['price_date'] = pd.to_datetime(df['price_date'])
    df = df.sort_values('price_date')

    # Define features and target
    feature_cols = ['current_price', 'sma_7', 'sma_30', 'daily_return_pct']
    target_col = 'target_price_7d'
    
    X = df[feature_cols]
    y = df[target_col]

    # Use a hard date-based split (80% past for training, 20% most recent for testing)
    # This prevents "looking into the future" during training.
    cutoff_date = df['price_date'].quantile(0.8)
    
    train_mask = df['price_date'] < cutoff_date
    X_train, X_test = X[train_mask], X[~train_mask]
    y_train, y_test = y[train_mask], y[~train_mask]

    print(f"Split Date: {cutoff_date.date()}")
    print(f"Training set: {len(X_train):,} rows | Test set: {len(X_test):,} rows")

    # --------------------------------------------------------------------------
    # MODEL TRAINING
    # --------------------------------------------------------------------------
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

    # --------------------------------------------------------------------------
    # EVALUATION
    # --------------------------------------------------------------------------
    predictions = model.predict(X_test)
    mae = mean_absolute_error(y_test, predictions)
    rmse = np.sqrt(mean_squared_error(y_test, predictions))

    print("\n--- Model Evaluation Results (Out-of-Time Test) ---")
    print(f"Mean Absolute Error (MAE): ${mae:.4f}")
    print(f"Root Mean Squared Error (RMSE): ${rmse:.4f}")

    # --------------------------------------------------------------------------
    # ARTIFACT PERSISTENCE
    # --------------------------------------------------------------------------
    os.makedirs(model_output_dir, exist_ok=True)
    model_path = os.path.join(model_output_dir, "xgboost_forecast.joblib")
    
    artifact = {
        "model": model,
        "feature_cols": feature_cols,
        "metrics": {
            "mae": mae, 
            "rmse": rmse,
            "split_date": str(cutoff_date.date())
        }
    }
    
    joblib.dump(artifact, model_path)
    print(f"Model successfully saved to: {model_path}")

if __name__ == "__main__":
    # Ensure script runs from the project root
    DB_PATH = os.path.join("data", "mtg_prices.duckdb")
    MODEL_DIR = os.path.join("models")
    
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}. Run ETL steps first.")
    else:
        train_xgboost_forecast(DB_PATH, MODEL_DIR)