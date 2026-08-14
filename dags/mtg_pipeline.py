from datetime import datetime, timedelta
from airflow import DAG  
from airflow.operators.bash import BashOperator  

default_args = {
    'owner': 'miguel',
    'depends_on_past': False,
    'start_date': datetime(2026, 8, 1),
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    'mtg_arbitrage_etl_pipeline',
    default_args=default_args,
    description='Daily MTG pricing ETL, feature engineering, and XGBoost training pipeline',
    schedule_interval='@daily',
    catchup=False,
) as dag:

    # Task 1: Ingest raw 1.2GB compressed JSON
    task_extract_raw = BashOperator(
        task_id='extract_raw_prices',
        bash_command='python /app/src/etl/download_raw.py',
    )

    # Task 2: Stream parse into DuckDB fact/dim tables
    task_load_duckdb = BashOperator(
        task_id='load_duckdb_tables',
        bash_command='python /app/src/etl/load_duckdb.py',
    )

    # Task 3: Execute SQL window functions (SMA, Spreads)
    task_build_features = BashOperator(
        task_id='build_financial_features',
        bash_command='python /app/src/analytics/build_features.py',
    )

    # Task 4: Retrain XGBoost model artifact
    task_train_model = BashOperator(
        task_id='train_xgboost_forecast',
        bash_command='python /app/src/analytics/train_forecast.py',
    )

    # Define the execution pipeline order (DAG dependencies)
    task_extract_raw >> task_load_duckdb >> task_build_features >> task_train_model