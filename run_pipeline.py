import os
import sys
import time
import datetime
import argparse
import subprocess
from pathlib import Path
import duckdb
import joblib

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False

BASE_DIR = Path(__file__).resolve().parent
RAW_JSON_PATH = BASE_DIR / "data" / "raw" / "AllPrices.json"
RAW_CARDS_CSV_PATH = BASE_DIR / "data" / "raw" / "cards.csv"
DB_PATH = BASE_DIR / "data" / "mtg_prices.duckdb"
MODEL_PATH = BASE_DIR / "models" / "xgboost_forecast.joblib"

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
            style="bold black on green" if passed else "bold white on red"
        )
        msg_text = f" [dim]({message})[/dim]" if message else ""
        console.print(f"  {status_text} [bold white]{substep}[/bold white]{msg_text}")
    else:
        status = "OK" if passed else "REBUILD NEEDED"
        extra = f" ({message})" if message else ""
        print(f"  [{status:<14}] {substep}{extra}")

def check_step_a() -> bool:
    """Verify raw MTGJSON JSON/CSV downloads exist and are uncorrupted."""
    compressed_json = BASE_DIR / "data" / "raw" / "AllPrices.json.xz"
    if not (RAW_JSON_PATH.exists() or compressed_json.exists()) or not RAW_CARDS_CSV_PATH.exists():
        log_status("Raw data feeds presence", False, "Missing AllPrices.json(.xz) or cards.csv")
        return False
    target = RAW_JSON_PATH if RAW_JSON_PATH.exists() else compressed_json
    file_size_mb = target.stat().st_size / (1024 * 1024)
    if file_size_mb < 300:
        log_status("Raw file payload (>300MB)", False, f"{file_size_mb:.1f} MB found")
        return False
    log_status("Raw data feeds presence", True, f"Payload: {file_size_mb:.1f} MB | CSV present")
    return True

def check_step_b(skip_freshness: bool = False) -> bool:
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

def check_step_c() -> bool:
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
        log_status("Feature store & spread tables", True, f"Train set: {train_count:,} | Spreads: {arb_count:,}")
        return True
    except Exception as e:
        log_status("Feature tables check", False, str(e))
        return False

def check_step_d() -> bool:
    if not MODEL_PATH.exists():
        log_status("Model artifact file", False, "xgboost_forecast.joblib missing")
        return False
    try:
        artifact = joblib.load(MODEL_PATH)
        if ("classifier" not in artifact and "model" not in artifact) or "metrics" not in artifact:
            log_status("Model artifact schema", False, "Invalid artifact structure")
            return False
        metrics = artifact["metrics"]
        mae = metrics.get("mae_pct", metrics.get("mae", 0.0))
        tau = metrics.get("prob_threshold", None)
        acc = metrics.get("directional_accuracy_pct", None)
        edge_msg = f"MAE: {mae:.2f}% | tau: {tau} | DirAcc: {acc}%" if tau else f"MAE: {mae:.2f}%"
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
    if HAS_RICH:
        console.print(f"  [bold green]✓[/bold green] Finished [cyan]{script_path.name}[/cyan] in [bold cyan]{elapsed:.2f}s[/bold cyan]\n")
    else:
        print(f"Finished {script_path.name} in {elapsed:.2f}s\n")

def print_header():
    if HAS_RICH:
        header_grid = Table.grid(expand=True)
        header_grid.add_column(justify="left", ratio=3)
        header_grid.add_column(justify="right", ratio=2)
        title = Text()
        title.append("TIAMAT QUANT ARBITRAGE TERMINAL", style="bold cyan")
        title.append(" │ ", style="dim white")
        title.append("Unified Pipeline Orchestrator", style="bold white")
        title.append("\nAutomated Data Ingestion • Feature Generation • Model Training • Backtest", style="dim italic")
        meta = Text()
        meta.append(f"Platform: {sys.platform}  \n", style="dim white")
        meta.append("Orchestrator: [bold green]Active[/bold green]")
        header_grid.add_row(title, meta)
        console.print(Panel(header_grid, box=box.ROUNDED, border_style="cyan", padding=(0, 1)))
        console.print()
    else:
        print("=" * 70)
        print(" TIAMAT QUANT ARBITRAGE TERMINAL │ UNIFIED PIPELINE ORCHESTRATOR")
        print("=" * 70)

def print_completion():
    if HAS_RICH:
        table = Table(box=box.ROUNDED, border_style="green", expand=True, show_header=True, header_style="bold green")
        table.add_column("Subsystem Service", style="bold white", ratio=2)
        table.add_column("Terminal CLI Command", style="bold cyan", ratio=3)
        table.add_column("Operational Function", style="dim", ratio=3)
        table.add_row("Start Analytics API", "python src/api/main.py", "FastAPI Microservice (Port 8000)")
        table.add_row("Start Terminal UI", "npm run dev", "Next.js 15 Web Client (Port 3000)")
        table.add_row("Run Market Scanner", "python src/analytics/scan_market.py", "Live CLI Arbitrage & Alpha Scanner")
        table.add_row("Execute Out-of-Time Backtest", "python src/analytics/backtest.py", "Scorecard & Loss Shield Evaluation")
        console.print(Panel(table, title="[bold green]PIPELINE EXECUTION COMPLETE[/bold green]", box=box.ROUNDED, border_style="green"))
    else:
        print("\n" + "=" * 70)
        print(" PIPELINE EXECUTION COMPLETE")
        print("  Start API server : python src/api/main.py")
        print("  Start Frontend   : npm run dev")
        print("  Scan Market      : python src/analytics/scan_market.py")
        print("  Run Backtest     : python src/analytics/backtest.py")
        print("=" * 70 + "\n")

def main():
    parser = argparse.ArgumentParser(description="Unified pipeline runner for secondary pricing ETL and forecasting pipeline")
    parser.add_argument("--force", "-f", action="store_true", help="Force re-run of all pipeline stages")
    parser.add_argument("--analytics-only", "-a", action="store_true", help="Skip raw ETL; run feature build and model training")
    parser.add_argument("--build-only", action="store_true", help="Only run SQL feature engineering")
    parser.add_argument("--train-only", action="store_true", help="Only run model training")
    parser.add_argument("--backtest", "-b", action="store_true", help="Run backtest after training")
    parser.add_argument("--backtest-only", action="store_true", help="Only run the backtest engine")
    parser.add_argument("--hurdle", type=float, default=10.0, help="Backtest minimum net ROI %% hurdle (default: 10.0)")
    parser.add_argument("--skip-freshness", action="store_true", help="Allow stale data older than 3 days")
    args = parser.parse_args()

    print_header()

    if args.backtest_only:
        log_step("Quantitative Backtest", "STEP E")
        execute_script(BASE_DIR / "src" / "analytics" / "backtest.py", ["--hurdle", str(args.hurdle)])
        return

    if not (args.analytics_only or args.build_only or args.train_only):
        log_step("Raw Feed Download", "STEP A")
        if args.force or not check_step_a():
            execute_script(BASE_DIR / "src" / "etl" / "download_raw.py")
        else:
            if HAS_RICH:
                console.print("  [dim green]●[/dim green] Raw data up to date. Skipping step.\n")
            else:
                print("  Raw data up to date. Skipping.\n")

        log_step("DuckDB Ingestion & Hampel MAD Filter", "STEP B")
        if args.force or not check_step_b(skip_freshness=args.skip_freshness):
            execute_script(BASE_DIR / "src" / "etl" / "load_duckdb.py")
        else:
            if HAS_RICH:
                console.print("  [dim green]●[/dim green] DuckDB fact/dim tables up to date. Skipping step.\n")
            else:
                print("  DuckDB fact/dim tables up to date. Skipping.\n")
    else:
        if HAS_RICH:
            console.print("  [dim yellow]●[/dim yellow] Skipping Raw ETL stages.\n")
        else:
            print("Skipping Raw ETL stages.\n")

    if not args.train_only:
        log_step("Feature Store & Temporal ASOF Assembly", "STEP C")
        if args.force or args.analytics_only or args.build_only or not check_step_c():
            execute_script(BASE_DIR / "src" / "analytics" / "build_features.py")
        else:
            if HAS_RICH:
                console.print("  [dim green]●[/dim green] Feature store up to date. Skipping step.\n")
            else:
                print("  Feature store up to date. Skipping.\n")

    if not args.build_only:
        log_step("Model Training & Conformal Calibration", "STEP D")
        if args.force or args.analytics_only or args.train_only or not check_step_d():
            execute_script(BASE_DIR / "src" / "analytics" / "train_forecast.py")
        else:
            if HAS_RICH:
                console.print("  [dim green]●[/dim green] Model artifact up to date. Skipping step.\n")
            else:
                print("  Model artifact up to date. Skipping.\n")

    if args.backtest:
        log_step("Quantitative Backtest", "STEP E")
        execute_script(BASE_DIR / "src" / "analytics" / "backtest.py", ["--hurdle", str(args.hurdle)])

    print_completion()

if __name__ == "__main__":
    main()