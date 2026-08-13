import os
import sys
import time
import argparse
import subprocess
import duckdb
import joblib
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RAW_JSON_PATH = BASE_DIR / "data" / "raw" / "AllPrices.json"
RAW_CARDS_CSV_PATH = BASE_DIR / "data" / "raw" / "cards.csv"
DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"
MODEL_PATH = BASE_DIR / "models" / "xgboost_forecast.joblib"

def log_step(title):
    print(f"\n============================================================")
    print(f" 🚀 {title}")
    print(f"============================================================")

def log_status(substep, passed, message=""):
    symbol = "  [✓] " if passed else "  [⚡] "
    status = "EXISTS / VALID" if passed else "MISSING / REBUILDING"
    print(f"{symbol}{substep:<45} -> {status} {f'({message})' if message else ''}")

def check_step_a():
    """Step A Check: Raw Payload Download & Decompression"""
    if not RAW_JSON_PATH.exists() or not RAW_CARDS_CSV_PATH.exists():
        log_status("Substep A.1: Raw data feeds existence", False)
        return False
    
    file_size_mb = RAW_JSON_PATH.stat().st_size / (1024 * 1024)
    if file_size_mb < 100:
        log_status("Substep A.2: File size verification (>100MB)", False, f"{file_size_mb:.1f} MB found")
        return False

    log_status("Substep A.1: Raw data feeds existence", True)
    log_status("Substep A.2: File size verification (>100MB)", True, f"{file_size_mb:.1f} MB")
    return True

def check_step_b():
    """Step B Check: DuckDB Ingestion & Table Loading"""
    if not DB_PATH.exists():
        log_status("Substep B.1: DuckDB database file existence", False)
        return False
    try:
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
        if "fact_prices" not in tables or "dim_cards" not in tables:
            log_status("Substep B.2: 'fact_prices' and 'dim_cards' existence", False)
            conn.close()
            return False
            
        count = conn.execute("SELECT COUNT(*) FROM fact_prices").fetchone()[0]
        dim_count = conn.execute("SELECT COUNT(*) FROM dim_cards").fetchone()[0]
        conn.close()

        if count == 0 or dim_count == 0:
            log_status("Substep B.3: Table row counts (>0)", False)
            return False

        log_status("Substep B.1: DuckDB database file existence", True)
        log_status("Substep B.2: 'fact_prices' and 'dim_cards' existence", True)
        log_status("Substep B.3: Table row counts", True, f"Fact: {count:,} | Dim: {dim_count:,}")
        return True
    except Exception as e:
        log_status("Substep B: Database check error", False, str(e))
        return False

def check_step_c():
    """Step C Check: SQL Feature Engineering & Analytical Tables"""
    if not DB_PATH.exists():
        log_status("Substep C.1: Analytical feature tables existence", False)
        return False
    try:
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
        required_tables = [
            "fact_card_features", 
            "fact_training_dataset", 
            "fact_arbitrage_opportunities"
        ]
        missing = [t for t in required_tables if t not in tables]
        if missing:
            log_status("Substep C.1: Required feature tables existence", False, f"Missing: {missing}")
            conn.close()
            return False

        train_count = conn.execute("SELECT COUNT(*) FROM fact_training_dataset").fetchone()[0]
        arb_count = conn.execute("SELECT COUNT(*) FROM fact_arbitrage_opportunities").fetchone()[0]
        conn.close()

        log_status("Substep C.1: Feature & Arbitrage tables existence", True)
        log_status("Substep C.2: Training dataset row count", True, f"{train_count:,} rows")
        log_status("Substep C.3: Arbitrage opportunities logged", True, f"{arb_count:,} spreads")
        return True
    except Exception as e:
        log_status("Substep C: Feature check error", False, str(e))
        return False

def check_step_d():
    """Step D Check: Trained XGBoost Model Artifact"""
    if not MODEL_PATH.exists():
        log_status("Substep D.1: Model artifact existence", False)
        return False
    try:
        artifact = joblib.load(MODEL_PATH)
        if "model" not in artifact or "metrics" not in artifact:
            log_status("Substep D.2: Artifact schema validation", False)
            return False

        mae = artifact["metrics"].get("mae", 0.0)
        log_status("Substep D.1: Model artifact existence", True)
        log_status("Substep D.2: Model artifact integrity check", True, f"Loaded Model MAE: ${mae:.4f}")
        return True
    except Exception as e:
        log_status("Substep D: Model load check error", False, str(e))
        return False

def execute_script(script_path):
    """Runs a Python script as a subprocess and streams output"""
    start_time = time.time()
    result = subprocess.run([sys.executable, str(script_path)], check=True)
    elapsed = time.time() - start_time
    print(f"\n  ⏱️ Script [{script_path.name}] completed in {elapsed:.2f} seconds.")

def main():
    parser = argparse.ArgumentParser(description="Unified Idempotent Local Pipeline Runner")
    parser.add_argument("--force", "-f", action="store_true", help="Force re-execution of ALL steps from scratch.")
    args = parser.parse_args()

    print("============================================================")
    print(" 🛠️ STARTING UNIFIED LOCAL PIPELINE RUNNER")
    print("============================================================")

    log_step("STEP A: Checking Raw Data Feed (ETL Ingestion)")
    if args.force or not check_step_a():
        print("\n  Executing Step A (download_raw.py)...")
        execute_script(BASE_DIR / "src" / "etl" / "download_raw.py")
    else:
        print("  ⏩ Skipping Step A — Raw data payloads are already downloaded & extracted.")

    log_step("STEP B: Checking DuckDB Ingestion (load_duckdb.py)")
    if args.force or not check_step_b():
        print("\n  Executing Step B (load_duckdb.py)...")
        execute_script(BASE_DIR / "src" / "etl" / "load_duckdb.py")
    else:
        print("  ⏩ Skipping Step B — DuckDB 'fact_prices' and 'dim_cards' tables are populated.")

    log_step("STEP C: Checking Feature Engineering (build_features.py)")
    if args.force or not check_step_c():
        print("\n  Executing Step C (build_features.py)...")
        execute_script(BASE_DIR / "src" / "analytics" / "build_features.py")
    else:
        print("  ⏩ Skipping Step C — Feature tables & Arbitrage views already built.")

    log_step("STEP D: Checking XGBoost Model Training (train_forecast.py)")
    if args.force or not check_step_d():
        print("\n  Executing Step D (train_forecast.py)...")
        execute_script(BASE_DIR / "src" / "analytics" / "train_forecast.py")
    else:
        print("  ⏩ Skipping Step D — Trained model artifact exists and is ready for inference.")

    print("\n============================================================")
    print(" 🎉 PIPELINE EXECUTION COMPLETE!")
    print(" You can now run the API microservice using:")
    print("   python src/api/main.py")
    print("============================================================")

if __name__ == "__main__":
    main()