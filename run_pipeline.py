"""
CLI runner for the MTG financial arbitrage and forecasting pipeline.

Executes and verifies sequential stages:
  - Step A: Download & decompress MTGJSON feeds (download_raw.py)
  - Step B: Streaming batch ingestion into DuckDB (load_duckdb.py)
  - Step C: Columnar feature engineering & ASOF windowing (build_features.py)
  - Step D: Two-stage hurdle XGBoost training & threshold tuning (train_forecast.py)
  - Step E: Friction-calibrated backtest (backtest.py)
"""

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
    print(f"\n--- {title} ---")


def log_status(substep: str, passed: bool, message: str = ""):
    status = "OK" if passed else "REBUILD NEEDED"
    extra = f" ({message})" if message else ""
    print(f"  [{status:<14}] {substep}{extra}")


def check_step_a() -> bool:
    """Verify raw MTGJSON JSON/CSV downloads exist and are uncorrupted."""
    if not RAW_JSON_PATH.exists() or not RAW_CARDS_CSV_PATH.exists():
        log_status("Raw data feeds present", False)
        return False

    file_size_mb = RAW_JSON_PATH.stat().st_size / (1024 * 1024)
    if file_size_mb < 300:
        log_status("Raw file size check (>300MB)", False, f"{file_size_mb:.1f} MB found")
        return False

    log_status("Raw data feeds present", True)
    log_status("Raw file size check (>300MB)", True, f"{file_size_mb:.1f} MB")
    return True


def check_step_b(skip_freshness: bool = False) -> bool:
    """Verify DuckDB fact_prices and dim_cards tables exist and are populated."""
    if not DB_PATH.exists():
        log_status("DuckDB database file", False)
        return False

    try:
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
        if "fact_prices" not in tables or "dim_cards" not in tables:
            log_status("fact_prices and dim_cards tables", False)
            conn.close()
            return False

        count = conn.execute("SELECT COUNT(*) FROM fact_prices").fetchone()[0]
        dim_count = conn.execute("SELECT COUNT(*) FROM dim_cards").fetchone()[0]

        if count == 0 or dim_count == 0:
            log_status("Table row count (>0)", False)
            conn.close()
            return False

        max_date_res = conn.execute("SELECT MAX(price_date) FROM fact_prices").fetchone()[0]
        conn.close()

        if max_date_res is None:
            log_status("Price data freshness", False, "No dates recorded")
            return False

        if isinstance(max_date_res, str):
            max_date = datetime.datetime.strptime(max_date_res, "%Y-%m-%d").date()
        elif isinstance(max_date_res, datetime.datetime):
            max_date = max_date_res.date()
        else:
            max_date = max_date_res

        if not skip_freshness:
            days_lag = (datetime.date.today() - max_date).days
            if days_lag > 3:
                log_status(
                    "Price data freshness",
                    False,
                    f"Data is {days_lag} days old (latest: {max_date})",
                )
                return False
            log_status("Price data freshness", True, f"Latest: {max_date}")
        else:
            log_status("Price data freshness", True, f"Skipped (Latest: {max_date})")

        log_status("DuckDB database file", True)
        log_status("Tables fact_prices and dim_cards", True, f"Fact: {count:,} | Dim: {dim_count:,}")
        return True

    except Exception as e:
        log_status("Database integrity check", False, str(e))
        return False


def check_step_c() -> bool:
    """Verify analytical feature tables and ASOF views exist."""
    if not DB_PATH.exists():
        log_status("Feature tables check", False, "Database missing")
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
            log_status("Feature tables presence", False, f"Missing: {missing}")
            conn.close()
            return False

        train_count = conn.execute("SELECT COUNT(*) FROM fact_training_dataset").fetchone()[0]
        arb_count = conn.execute("SELECT COUNT(*) FROM fact_arbitrage_opportunities").fetchone()[0]
        conn.close()

        if train_count == 0:
            log_status("Feature dataset populated", False, "Zero labeled training rows")
            return False

        log_status("Feature & Arbitrage tables", True, f"Train: {train_count:,} | Arb spreads: {arb_count:,}")
        return True

    except Exception as e:
        log_status("Feature tables check", False, str(e))
        return False


def check_step_d() -> bool:
    """Verify saved XGBoost model artifact is valid and readable."""
    if not MODEL_PATH.exists():
        log_status("Model artifact file", False)
        return False

    try:
        artifact = joblib.load(MODEL_PATH)
        if ("classifier" not in artifact and "model" not in artifact) or "metrics" not in artifact:
            log_status("Model artifact schema", False)
            return False

        metrics = artifact["metrics"]
        mae = metrics.get("mae_pct", metrics.get("mae", 0.0))
        naive_mae = metrics.get("naive_mae_pct", None)
        tau = metrics.get("prob_threshold", None)
        acc = metrics.get("directional_accuracy_pct", None)

        edge_msg = f"MAE: {mae:.2f}% | Baseline: {naive_mae:.2f}% | tau: {tau} | DirAcc: {acc}%" if naive_mae else f"MAE: {mae:.2f}%"
        log_status("Model artifact integrity", True, edge_msg)
        return True

    except Exception as e:
        log_status("Model artifact load", False, str(e))
        return False


def execute_script(script_path: Path, extra_args: list = None):
    start_time = time.time()
    cmd = [sys.executable, str(script_path)] + (extra_args or [])
    subprocess.run(cmd, check=True)
    elapsed = time.time() - start_time
    print(f"Finished {script_path.name} in {elapsed:.2f}s")


def main():
    parser = argparse.ArgumentParser(description="Unified pipeline runner for MTG pricing & ML forecast engine")
    parser.add_argument("--force", "-f", action="store_true", help="Force re-run of all pipeline stages")
    parser.add_argument("--analytics-only", "-a", action="store_true", help="Skip raw ETL; run feature build and model training")
    parser.add_argument("--build-only", action="store_true", help="Only run SQL feature engineering")
    parser.add_argument("--train-only", action="store_true", help="Only run model training")
    parser.add_argument("--backtest", "-b", action="store_true", help="Run backtest after training")
    parser.add_argument("--backtest-only", action="store_true", help="Only run the backtest engine")
    parser.add_argument("--hurdle", type=float, default=10.0, help="Backtest minimum net ROI %% hurdle (default: 10.0)")
    parser.add_argument("--skip-freshness", action="store_true", help="Allow stale data older than 3 days")
    args = parser.parse_args()

    print("Running MTG Analytics Pipeline...")

    if args.backtest_only:
        log_step("Step E: Quantitative Backtest")
        execute_script(BASE_DIR / "src" / "analytics" / "backtest.py", ["--hurdle", str(args.hurdle)])
        return

    # Raw ETL (Stages A & B)
    if not (args.analytics_only or args.build_only or args.train_only):
        log_step("Step A: Raw Feed Download (download_raw.py)")
        if args.force or not check_step_a():
            execute_script(BASE_DIR / "src" / "etl" / "download_raw.py")
        else:
            print("  Raw data up to date. Skipping.")

        log_step("Step B: DuckDB Ingestion (load_duckdb.py)")
        if args.force or not check_step_b(skip_freshness=args.skip_freshness):
            execute_script(BASE_DIR / "src" / "etl" / "load_duckdb.py")
        else:
            print("  DuckDB fact/dim tables up to date. Skipping.")
    else:
        print("Skipping Raw ETL stages.")

    # Feature Engineering (Stage C)
    if not args.train_only:
        log_step("Step C: Feature Engineering (build_features.py)")
        if args.force or args.analytics_only or args.build_only or not check_step_c():
            execute_script(BASE_DIR / "src" / "analytics" / "build_features.py")
        else:
            print("  Feature store up to date. Skipping.")

    # Model Training (Stage D)
    if not args.build_only:
        log_step("Step D: Model Training (train_forecast.py)")
        if args.force or args.analytics_only or args.train_only or not check_step_d():
            execute_script(BASE_DIR / "src" / "analytics" / "train_forecast.py")
        else:
            print("  Model artifact up to date. Skipping.")

    # Backtest (Stage E)
    if args.backtest:
        log_step("Step E: Quantitative Backtest (backtest.py)")
        execute_script(BASE_DIR / "src" / "analytics" / "backtest.py", ["--hurdle", str(args.hurdle)])

    print("\nPipeline finished successfully.")
    print("Start API server : python src/api/main.py")
    print("Start Frontend   : npm run dev\n")


if __name__ == "__main__":
    main()