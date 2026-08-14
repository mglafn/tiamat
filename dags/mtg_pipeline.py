import os
from pathlib import Path
from datetime import datetime, timedelta
from airflow import DAG  
from airflow.operators.bash import BashOperator  

BASE_DIR = Path(__file__).resolve().parent.parent

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

    task_extract_raw = BashOperator(
        task_id='extract_raw_prices',
        bash_command=f'python3 {BASE_DIR}/src/etl/download_raw.py',
    )

    task_load_duckdb = BashOperator(
        task_id='load_duckdb_tables',
        bash_command=f'python3 {BASE_DIR}/src/etl/load_duckdb.py',
    )

    task_build_features = BashOperator(
        task_id='build_financial_features',
        bash_command=f'python3 {BASE_DIR}/src/analytics/build_features.py',
    )

    task_train_model = BashOperator(
        task_id='train_xgboost_forecast',
        bash_command=f'python3 {BASE_DIR}/src/analytics/train_forecast.py',
    )

    task_extract_raw >> task_load_duckdb >> task_build_features >> task_train_model