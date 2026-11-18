import argparse
import datetime
import subprocess
import sys
import time
import duckdb
import joblib

from src.cli.console import HAS_RICH, Panel, Table, Text, box, console, print_banner, print_msg
from src.config import (
    ALL_PRICES_JSON_PATH,
    ALL_PRICES_XZ_PATH,
    BASE_DIR,
    CARDS_CSV_PATH,
    DB_PATH,
    MODEL_CONFIG,
    MODEL_PATH,
)


def log_step(title: str, step_num: str = ""):
    if HAS_RICH:
        t = Text()
        if step_num:
            t.append(f"[{step_num}] ", style="bold cyan")
        t.append(title.upper(), style="bold white")
        console.print(Panel(t, box=box.ROUNDED, border_style="cyan", padding=(0, 1)))
    else:
        prefix = f"[{step_num}] " if step_num else ""
        print(f"\n--- {prefix}{title} ---")


def log_status(substep: str, passed: bool, message: str = ""):
    if HAS_RICH:
        status_text = Text(
            " PASSED " if passed else " REBUILD ",
            style="bold black on green" if passed else "bold white on red",
        )
        msg_text = f" [dim]({message})[/dim]" if message else ""
        console.print(f"  {status_text} [bold white]{substep}[/bold white]{msg_text}")
    else:
        status = "OK" if passed else "REBUILD NEEDED"
        extra = f" ({message})" if message else ""
        print(f"  [{status:<14}] {substep}{extra}")


def raw_feeds_ready() -> bool:
    """Verify raw MTGJSON JSON/CSV downloads exist and are uncorrupted."""
    has_prices = ALL_PRICES_JSON_PATH.exists() or ALL_PRICES_XZ_PATH.exists()
    if not has_prices or not CARDS_CSV_PATH.exists():
        log_status("Raw data feeds presence", False, "Missing AllPrices.json(.xz) or cards.csv")
        return False
    target = ALL_PRICES_JSON_PATH if ALL_PRICES_JSON_PATH.exists() else ALL_PRICES_XZ_PATH
    file_size_mb = target.stat().st_size / (1024 * 1024)
    if file_size_mb < 300:
        log_status("Raw file payload (>300MB)", False, f"{file_size_mb:.1f} MB found")
        return False
    log_status("Raw data feeds presence", True, f"Payload: {file_size_mb:.1f} MB | CSV present")
    return True


def duckdb_tables_fresh(skip_freshness: bool = False) -> bool:
    if not DB_PATH.exists():
        log_status("DuckDB file existence", False, "mtg_prices.duckdb missing")
        return False
    try:
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
        if "fact_prices" not in tables or "dim_cards" not in tables:
            log_status("Primary schema validation", False, "fact_prices or dim_cards missing")
            conn.close()
            return False
        count = conn.execute("SELECT COUNT(*) FROM fact_prices").fetchone()[0]
        dim_count = conn.execute("SELECT COUNT(*) FROM dim_cards").fetchone()[0]
        if count == 0 or dim_count == 0:
            log_status("Table row count (>0)", False, "Zero records in database")
            conn.close()
            return False
        max_date_res = conn.execute("SELECT MAX(price_date) FROM fact_prices").fetchone()[0]
        conn.close()
        if max_date_res is None:
            log_status("Price data temporal freshness", False, "No dates recorded")
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
                    "Temporal freshness (<=3d)",
                    False,
                    f"{days_lag} days lag (Latest: {max_date})",
                )
                return False
            log_status("Temporal freshness (<=3d)", True, f"Latest: {max_date}")
        else:
            log_status("Temporal freshness (<=3d)", True, f"Bypassed (Latest: {max_date})")
        log_status("Fact & Dimension tables", True, f"Prices: {count:,} | Catalog: {dim_count:,}")
        return True
    except Exception as e:
        log_status("Database integrity check", False, str(e))
        return False


def feature_store_ready() -> bool:
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
            log_status("Analytical feature schema", False, f"Missing: {missing}")
            conn.close()
            return False
        train_count = conn.execute("SELECT COUNT(*) FROM fact_training_dataset").fetchone()[0]
        arb_count = conn.execute("SELECT COUNT(*) FROM fact_arbitrage_opportunities").fetchone()[0]
        conn.close()
        if train_count == 0:
            log_status("Feature dataset populated", False, "Zero labeled training rows")
            return False
        log_status(
            "Feature store & spread tables",
            True,
            f"Train set: {train_count:,} | Spreads: {arb_count:,}",
        )
        return True
    except Exception as e:
        log_status("Feature tables check", False, str(e))
        return False


def model_artifact_ready() -> bool:
    if not MODEL_PATH.exists():
        log_status("Model artifact file", False, "xgboost_forecast.joblib missing")
        return False
    try:
        artifact = joblib.load(MODEL_PATH)
        if "quantile_models" not in artifact or "metrics" not in artifact:
            log_status("Model artifact schema", False, "Invalid artifact structure")
            return False
        metrics = artifact["metrics"]
        mae = metrics.get("mae_pct", 0.0)
        tau = metrics.get("tau_buyer_radar", metrics.get("prob_threshold", None))
        parts = [f"MAE: {mae:.2f}%"]
        if tau is not None:
            parts.append(f"tau_buyer: {tau:.3f}")
        log_status("Model artifact integrity", True, " | ".join(parts))
        return True
    except Exception as e:
        log_status("Model artifact load", False, str(e))
        return False


def execute_module(module_name: str, extra_args: list = None):
    start_time = time.time()
    cmd = [sys.executable, "-m", module_name] + (extra_args or [])
    subprocess.run(cmd, cwd=str(BASE_DIR), check=True)
    elapsed = time.time() - start_time
    print_msg(
        f"  [bold green]✓[/bold green] Finished [cyan]{module_name}[/cyan] in [bold cyan]{elapsed:.2f}s[/bold cyan]\n",
        f"Finished {module_name} in {elapsed:.2f}s\n",
    )


def print_header():
    print_banner(
        "Unified Pipeline Orchestrator",
        "Automated Data Ingestion • Feature Generation • Model Training • Backtest",
        [
            f"[dim white]Platform: {sys.platform}[/dim white]",
            "Orchestrator: [bold green]Active[/bold green]",
        ],
        brand="TIAMAT QUANT ARBITRAGE TERMINAL",
    )


def print_completion():
    if HAS_RICH:
        table = Table(
            box=box.ROUNDED,
            border_style="green",
            expand=True,
            show_header=True,
            header_style="bold green",
        )
        table.add_column("Subsystem Service", style="bold white", ratio=2)
        table.add_column("Terminal CLI Command", style="bold cyan", ratio=3)
        table.add_column("Operational Function", style="dim", ratio=3)
        table.add_row(
            "Start Analytics API", "python -m src.api.main", "FastAPI Microservice (Port 8000)"
        )
        table.add_row("Start Terminal UI", "npm run dev", "Next.js Web Client (Port 3000)")
        table.add_row(
            "Run Market Scanner",
            "python -m src.analytics.scan_market",
            "Live CLI Arbitrage & Alpha Scanner",
        )
        table.add_row(
            "Execute Out-of-Time Backtest",
            "python -m src.analytics.backtest",
            "Scorecard & Loss Shield Evaluation",
        )
        console.print(
            Panel(
                table,
                title="[bold green]PIPELINE EXECUTION COMPLETE[/bold green]",
                box=box.ROUNDED,
                border_style="green",
            )
        )
    else:
        print("\n" + "=" * 70)
        print(" PIPELINE EXECUTION COMPLETE")
        print("  Start API server : python -m src.api.main")
        print("  Start Frontend   : npm run dev")
        print("  Scan Market      : python -m src.analytics.scan_market")
        print("  Run Backtest     : python -m src.analytics.backtest")
        print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Unified pipeline runner for secondary pricing ETL and forecasting pipeline"
    )
    parser.add_argument(
        "--force", "-f", action="store_true", help="Force re-run of all pipeline stages"
    )
    parser.add_argument(
        "--analytics-only",
        "-a",
        action="store_true",
        help="Skip raw ETL; run feature build and model training",
    )
    parser.add_argument(
        "--build-only", action="store_true", help="Only run SQL feature engineering"
    )
    parser.add_argument("--train-only", action="store_true", help="Only run model training")
    parser.add_argument(
        "--backtest", "-b", action="store_true", help="Run backtest after training"
    )
    parser.add_argument("--backtest-only", action="store_true", help="Only run the backtest engine")
    parser.add_argument(
        "--hurdle",
        type=float,
        default=MODEL_CONFIG["DEFAULT_ROI_HURDLE_PCT"],
        help="Backtest minimum net ROI %% hurdle",
    )
    parser.add_argument(
        "--skip-freshness", action="store_true", help="Allow stale data older than 3 days"
    )
    args = parser.parse_args()

    print_header()

    if args.backtest_only:
        log_step("Quantitative Backtest", "STEP E")
        execute_module("src.analytics.backtest", ["--hurdle", str(args.hurdle)])
        return

    if not (args.analytics_only or args.build_only or args.train_only):
        log_step("Raw Feed Download", "STEP A")
        if args.force or not raw_feeds_ready():
            execute_module("src.etl.download_raw")
        else:
            print_msg(
                "  [dim green]●[/dim green] Raw data up to date. Skipping step.\n",
                "  Raw data up to date. Skipping.\n",
            )

        log_step("DuckDB Ingestion & Hampel MAD Filter", "STEP B")
        if args.force or not duckdb_tables_fresh(skip_freshness=args.skip_freshness):
            execute_module("src.etl.load_duckdb")
        else:
            print_msg(
                "  [dim green]●[/dim green] DuckDB fact/dim tables up to date. Skipping step.\n",
                "  DuckDB fact/dim tables up to date. Skipping.\n",
            )
    else:
        print_msg(
            "  [dim yellow]●[/dim yellow] Skipping Raw ETL stages.\n",
            "Skipping Raw ETL stages.\n",
        )

    if not args.train_only:
        log_step("Feature Store & Temporal ASOF Assembly", "STEP C")
        if args.force or args.analytics_only or args.build_only or not feature_store_ready():
            execute_module("src.analytics.build_features")
        else:
            print_msg(
                "  [dim green]●[/dim green] Feature store up to date. Skipping step.\n",
                "  Feature store up to date. Skipping.\n",
            )

    if not args.build_only:
        log_step("Model Training & Quantile Calibration", "STEP D")
        if args.force or args.analytics_only or args.train_only or not model_artifact_ready():
            execute_module("src.analytics.train_forecast")
        else:
            print_msg(
                "  [dim green]●[/dim green] Model artifact up to date. Skipping step.\n",
                "  Model artifact up to date. Skipping.\n",
            )

    if args.backtest:
        log_step("Quantitative Backtest", "STEP E")
        execute_module("src.analytics.backtest", ["--hurdle", str(args.hurdle)])

    print_completion()


if __name__ == "__main__":
    main()