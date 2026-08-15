import os
import sys
import time
import datetime
import argparse
import subprocess
from pathlib import Path
import duckdb
import joblib

BASE_DIR = Path(__file__).resolve().parent
RAW_JSON_PATH = BASE_DIR / "data" / "raw" / "AllPrices.json"
RAW_CARDS_CSV_PATH = BASE_DIR / "data" / "raw" / "cards.csv"
DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"
MODEL_PATH = BASE_DIR / "models" / "xgboost_forecast.joblib"


def log_step(title: str):
    print("\n============================================================")
    print(f" 🚀 {title}")
    print("============================================================")


def log_status(substep: str, passed: bool, message: str = ""):
    symbol = "  [✓] " if passed else "  [⚡] "
    status = "EXISTS / VALID" if passed else "MISSING / REBUILDING"
    print(f"{symbol}{substep:<48} -> {status} {f'({message})' if message else ''}")


def check_step_a() -> bool:
    """Step A Check: Raw Payload Download & Decompression"""
    if not RAW_JSON_PATH.exists() or not RAW_CARDS_CSV_PATH.exists():
        log_status("Substep A.1: Raw data feeds existence", False)
        return False

    file_size_mb = RAW_JSON_PATH.stat().st_size / (1024 * 1024)
    if file_size_mb < 300:
        log_status("Substep A.2: File size verification (>300MB)", False, f"{file_size_mb:.1f} MB found")
        return False

    log_status("Substep A.1: Raw data feeds existence", True)
    log_status("Substep A.2: File size verification (>300MB)", True, f"{file_size_mb:.1f} MB")
    return True


def check_step_b(skip_freshness: bool = False) -> bool:
    """Step B Check: DuckDB Ingestion, Table Loading & Freshness"""
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

        if count == 0 or dim_count == 0:
            log_status("Substep B.3: Table row counts (>0)", False)
            conn.close()
            return False

        max_date_res = conn.execute("SELECT MAX(price_date) FROM fact_prices").fetchone()[0]
        conn.close()

        if max_date_res is None:
            log_status("Substep B.4: Price data freshness verification", False, "No dates logged")
            return False

        if isinstance(max_date_res, str):
            max_date = datetime.datetime.strptime(max_date_res, "%Y-%m-%d").date()
        elif isinstance(max_date_res, datetime.datetime):
            max_date = max_date_res.date()
        else:
            max_date = max_date_res

        if not skip_freshness:
            days_lag = (datetime.date.today() - max_date).days
            if days_lag > 2:
                log_status(
                    "Substep B.4: Price data freshness verification",
                    False,
                    f"Data is stale ({days_lag} days old, latest: {max_date})",
                )
                return False
            log_status("Substep B.4: Price data freshness verification", True, f"Latest date: {max_date}")
        else:
            log_status("Substep B.4: Price data freshness verification", True, f"SKIPPED (Latest: {max_date})")

        log_status("Substep B.1: DuckDB database file existence", True)
        log_status("Substep B.2: 'fact_prices' and 'dim_cards' existence", True)
        log_status("Substep B.3: Table row counts", True, f"Fact: {count:,} | Dim: {dim_count:,}")
        return True

    except Exception as e:
        log_status("Substep B: Database check error", False, str(e))
        return False


def check_step_c() -> bool:
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
            "fact_arbitrage_opportunities",
        ]
        missing = [t for t in required_tables if t not in tables]
        if missing:
            log_status("Substep C.1: Required feature tables existence", False, f"Missing: {missing}")
            conn.close()
            return False

        train_count = conn.execute("SELECT COUNT(*) FROM fact_training_dataset").fetchone()[0]
        arb_count = conn.execute("SELECT COUNT(*) FROM fact_arbitrage_opportunities").fetchone()[0]
        conn.close()

        if train_count == 0:
            log_status("Substep C.2: Analytical dataset synchronization", False, "Empty feature tables")
            return False

        log_status("Substep C.1: Feature & Arbitrage tables existence", True)
        log_status("Substep C.2: Training dataset row count", True, f"{train_count:,} rows")
        log_status("Substep C.3: Arbitrage opportunities logged", True, f"{arb_count:,} spreads")
        return True

    except Exception as e:
        log_status("Substep C: Feature check error", False, str(e))
        return False


def check_step_d() -> bool:
    """Step D Check: Trained XGBoost Model Artifact & Schema Validation"""
    if not MODEL_PATH.exists():
        log_status("Substep D.1: Model artifact existence", False)
        return False

    try:
        artifact = joblib.load(MODEL_PATH)
        if "model" not in artifact or "metrics" not in artifact:
            log_status("Substep D.2: Artifact schema validation", False)
            return False

        metrics = artifact["metrics"]
        mae = metrics.get("mae_pct", metrics.get("mae", 0.0))
        naive_mae = metrics.get("naive_mae_pct", None)

        log_status("Substep D.1: Model artifact existence", True)
        edge_msg = f"MAE: {mae:.2f}% | Baseline: {naive_mae:.2f}%" if naive_mae else f"MAE: {mae:.2f}%"
        log_status("Substep D.2: Model artifact integrity", True, edge_msg)
        return True

    except Exception as e:
        log_status("Substep D: Model load check error", False, str(e))
        return False


def execute_script(script_path: Path):
    start_time = time.time()
    subprocess.run([sys.executable, str(script_path)], check=True)
    elapsed = time.time() - start_time
    print(f"\n  ⏱️ Script [{script_path.name}] completed in {elapsed:.2f} seconds.")


def main():
    parser = argparse.ArgumentParser(description="Unified Idempotent Local Pipeline Runner")
    parser.add_argument("--force", "-f", action="store_true", help="Force re-execution of selected steps.")
    parser.add_argument("--analytics-only", "-a", action="store_true", help="Skip raw ETL and run Feature Engineering + Training.")
    parser.add_argument("--build-only", action="store_true", help="Only run SQL Feature Engineering.")
    parser.add_argument("--train-only", action="store_true", help="Only run XGBoost Model Training.")
    parser.add_argument("--skip-freshness", action="store_true", help="Do not fail ETL if historical prices are older than 2 days.")
    args = parser.parse_args()

    print("============================================================")
    print(" 🛠️ STARTING UNIFIED LOCAL PIPELINE RUNNER")
    print("============================================================")

    if not (args.analytics_only or args.build_only or args.train_only):
        log_step("STEP A: Checking Raw Data Feed (ETL Ingestion)")
        if args.force or not check_step_a():
            print("\n  Executing Step A (download_raw.py)...")
            execute_script(BASE_DIR / "src" / "etl" / "download_raw.py")
        else:
            print("  ⏩ Skipping Step A — Raw data payloads are already downloaded & extracted.")

        log_step("STEP B: Checking DuckDB Ingestion (load_duckdb.py)")
        if args.force or not check_step_b(skip_freshness=args.skip_freshness):
            print("\n  Executing Step B (load_duckdb.py)...")
            execute_script(BASE_DIR / "src" / "etl" / "load_duckdb.py")
        else:
            print("  ⏩ Skipping Step B — DuckDB 'fact_prices' and 'dim_cards' tables are ready.")
    else:
        print("\n  ⏩ Skipping Raw Ingestion Steps A & B (Targeting Analytics/Training only).")

    if not args.train_only:
        log_step("STEP C: Checking Feature Engineering (build_features.py)")
        if args.force or args.analytics_only or args.build_only or not check_step_c():
            print("\n  Executing Step C (build_features.py)...")
            execute_script(BASE_DIR / "src" / "analytics" / "build_features.py")
        else:
            print("  ⏩ Skipping Step C — Feature tables & Arbitrage views are up to date.")

    if not args.build_only:
        log_step("STEP D: Checking XGBoost Model Training (train_forecast.py)")
        if args.force or args.analytics_only or args.train_only or not check_step_d():
            print("\n  Executing Step D (train_forecast.py)...")
            execute_script(BASE_DIR / "src" / "analytics" / "train_forecast.py")
        else:
            print("  ⏩ Skipping Step D — Trained model artifact is up to date.")

    print("\n============================================================")
    print(" 🎉 PIPELINE EXECUTION COMPLETE!")
    print(" Run the API microservice with: python src/api/main.py")
    print("============================================================")


if __name__ == "__main__":
    main()