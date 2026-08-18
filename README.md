
# MTG Quant Terminal · Financial Arbitrage & Price Forecasting Engine

[![CI Pipeline](https://github.com/mglafn/mtg-financial-arbitrage/actions/workflows/ci.yml/badge.svg)](https://github.com/mglafn/mtg-financial-arbitrage/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![DuckDB](https://img.shields.io/badge/DuckDB-OLAP%20Store-FFF000.svg)](https://duckdb.org/)
[![Next.js 15](https://img.shields.io/badge/Next.js-15-black.svg)](https://nextjs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An institutional-grade quantitative pipeline, REST microservice, and real-time trading terminal engineered to identify cross-market arbitrage divergences and forecast 7-day asset price returns across secondary collectible markets.

Processes high-cardinality MTGJSON pricing feeds (>1.2GB) with a sub-150MB memory footprint using streaming ETL (`ijson`), in-memory columnar windowing in DuckDB, and a two-stage hurdle XGBoost predictive model calibrated against real-world fulfillment frictions.

---

## System Architecture

```
[Raw MTGJSON Feed (>1.2GB)] 
            │
      (Streaming ijson ETL)
            ▼
┌────────────────────────────────────────────────────────┐
│               DuckDB Analytical Engine                 │
├────────────────────────────────────────────────────────┤
│ • fact_prices (Raw multi-vendor ledger)               │
│ • dim_cards   (Dimensional metadata & fundamentals)    │
│ • fact_card_features (Calendar-aware rolling SMAs)     │
│ • fact_training_dataset (7–14D forward returns)        │
│ • fact_arbitrage_opportunities (Temporal ASOF Joins)   │
└───────────────────────────┬────────────────────────────┘
                            │
              (14-Day Embargoed Partitions)
                            ▼
┌────────────────────────────────────────────────────────┐
│           Two-Stage Hurdle XGBoost Engine              │
├────────────────────────────────────────────────────────┤
│ • Stage 1: XGBClassifier -> P(|Δ| ≥ 4.5%)              │
│ • Stage 2: XGBRegressor (L1 Loss) -> Return Magnitude  │
│ • Threshold Gate: τ = 0.89 (Validation-Calibrated)    │
└───────────────────────────┬────────────────────────────┘
                            │
                 (FastAPI REST Microservice)
                            │
               ┌────────────┴────────────┐
               ▼                         ▼
    [Next.js Trading Terminal]   [Quantitative Backtester]
    (Real-time Telemetry, SVG    (Piecewise Frictions, κ_risk,
     Linear Charting, ⌘K Nav)     Dead-Zone Fee Clamping)
```

---

## Key Design Decisions & Quantitative Architecture

### 1. Memory-Safe Streaming Ingestion (`ijson` + DuckDB)
- Lazily streams deeply nested pricing records from `AllPrices.json` using generator-based `ijson.kvitems` chunking.
- Batches and ingests 50,000-record dataframes into columnar DuckDB storage, ensuring memory consumption stays strictly under **150MB RAM** during 1.2GB+ file ingestion.

### 2. Analytical Feature Store & Temporal ASOF Windowing
- Computes calendar-aware rolling indicators (`SMA-7`, `SMA-30`, 14-day rolling return volatility, spread velocity, active vendor deltas) using SQL window functions (`RANGE BETWEEN INTERVAL`).
- Implements **DuckDB `ASOF JOIN`** to align asynchronous Card Kingdom buylist offers with the most recent preceding TCGplayer retail price ($\le 3$ days lag), eliminating temporal lookahead bias during spread valuation.

### 3. Two-Stage Hurdle Predictive Architecture
- **The Zero-Inflation Problem:** Over 65% of liquid collectible assets exhibit stationary ($0.00\%$) 7-day returns. Single continuous regressors fail by predicting non-zero fractional noise ($\pm 0.15\%$), accumulating heavy MAE penalties against flat actuals.
- **Stage 1 (Catalyst Classifier):** An `XGBClassifier` with `scale_pos_weight` estimates breakout probability $P(|\Delta| \ge 4.50\%)$.
- **Stage 2 (Magnitude Regressor):** An `XGBRegressor` trained strictly on verified movers using L1 loss (`reg:absoluteerror`).
- **Validation Calibration:** Probability cutoff threshold ($\tau = 0.89$) is calibrated strictly on validation partitions to minimize MAE against naive zero-return baselines.

### 4. Target Leakage Prevention & Anti-Leakage Embargoes
- Enforces strict chronological 3-way dataset partitioning (Train / Validation / Test).
- Inserts **14-day non-overlapping calendar embargoes** between partitions to completely isolate the 7-to-14 day forward target window, preventing multi-day return leakage across splits.

### 5. Universe Sanitation & Signal Pruning
- **Penny-Asset Noise Reduction:** Prunes sub-$2.50 bulk singles from the training universe. Sub-$0.10 penny assets exhibiting +300% to +400% nominal fluctuations ($0.05 → $0.20) heavily distort regression loss gradients without representing liquid, tradeable market alpha.
- **Outlier Truncation:** Binds forward return targets to $[-50.0\%, +150.0\%]$ to eliminate phantom listing spikes, scraper anomalies, and buybox spoofing artifacts.
- **Friction-Aware Exclusion:** Excludes sub-$0.40 assets at the ingestion layer due to marketplace fee mechanics (TCGplayer Direct 50% fee cliff renders sub-$0.40 assets economically untradeable).
- **Hurdle-Based Signal Pruning ($\tau$):** Inactive and low-conviction predictions are systematically pruned to $0.00\%$ return unless the Stage 1 classifier breaches the validation-tuned confidence threshold ($\tau = 0.89$), directly solving the zero-inflation penalty across stationary assets.

### 6. Friction-Calibrated Unit Economics
- **TCGplayer Direct Rate Card:** Implements exact piecewise fee mechanics:
  $$\text{Payout}(P) = \begin{cases} 
  0.00 & P < \$0.40 \\ 
  0.50 \cdot P & \$0.40 \le P < \$2.50 \\ 
  P - [1.12 + \min(0.0895 \cdot P, 75) + 0.025 \cdot P \cdot (1 + \tau_{\text{tax}})] & P \ge \$2.50 
  \end{cases}$$
- **Dead-Zone Price Clamping:** Exit prices in the $[\$2.50, \$2.67]$ range yield lower net returns than $\$2.49$ due to the $\$1.12$ fixed fee cliff. The engine automatically clamps exit targets in this window to $\$2.49$.
- **Condition Downgrade Risk Haircut ($\kappa_{\text{risk}}$):** Models intake grading attrition at centralized authentication hubs (3.5% NM $\rightarrow$ LP downgrade penalty, 0.5% counterfeit/damage rejection, 75% inventory salvage recovery).
- **Accounting Standard:** Enforces IEEE 754 Banker's Rounding (`ROUND_HALF_EVEN`) across all ledger operations.

---

## Model Benchmark & Evolution Progression

| Milestone / Iteration | Dataset Size | Architecture / Loss | Validation Strategy | Model MAE | Naive Baseline | Directional Acc. | Quality Gate |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **Iteration 1: Raw Baseline** | 47.8M | Single `XGBRegressor` (MSE) | Chronological 80/20 | 5.72% | 5.40% | 52.4% | ❌ Failed (-32.0 bps) |
| **Iteration 2: Windowing** | 47.8M | Single `XGBRegressor` (L1) | Chronological 80/20 | 5.43% | 5.40% | 55.7% | ❌ Failed (-3.0 bps) |
| **Iteration 3: Sanitation** | 12.1M | Single `XGBRegressor` (L1+Reg) | Chronological 80/20 | 3.96% | 3.92% | 58.1% | ❌ Failed (-4.0 bps) |
| **Milestone 1: Leak Sweep** | 12.1M | Single Regressor + Deadband | Swept on Test Split | 3.91% | 3.92% | 72.6% | ⚠️ Invalid (Leakage) |
| **Milestone 2: 3-Way Split** | 10.0M | Single Regressor + Deadband | 3-Way + 8d Embargo | 3.94% | 3.84% | 65.5% | ❌ Failed (-10.0 bps) |
| **Milestone 3: Feature Store** | 2.97M | Single Regressor (Expanded) | 3-Way + 8d Embargo | 3.95% | 3.93% | 69.1% | ❌ Failed (Peg Trap) |
| **Milestone 4: Two-Stage Hurdle** | 2.97M | Hurdle (Clf + L1 Reg) | 3-Way + 8d Embargo | **3.9047%** | 3.9280% | 69.06% | ✅ Passed (+2.33 bps) |
| **Milestone 5: Production** | 2.97M | Hurdle (Clf + L1 Reg) | **3-Way + 14d Embargo**| **4.0177%** | **4.0389%** | **66.50%** | ✅ Passed (+2.12 bps) |
| **Milestone 6: Hardened (Live)** | 2.97M | **Two-Stage Hurdle ($\tau=0.89$)**| **3-Way + 14d + $\kappa_{\text{risk}}$** | **4.0177%** | **4.0389%** | **66.50%** | ✅ **Production Ready** |

---

## Tech Stack

| Layer | Technologies |
| :--- | :--- |
| **Data Engineering & ETL** | Python 3.10+, `ijson` (Streaming JSON), DuckDB (Columnar OLAP), Pandas, NumPy, Airflow |
| **Machine Learning & Analytics** | XGBoost, Scikit-Learn, Statsmodels, Joblib |
| **Backend & Microservices** | FastAPI, Uvicorn, Pydantic v2, Pyodps, PyTest |
| **Frontend & Terminal UI** | Next.js 15 (App Router), React 19, Tailwind CSS v4, SWR, Lucide Icons |
| **Infrastructure & CI/CD** | Docker, GitHub Actions CI (Black, Flake8, PyTest) |

---

## Directory Structure

```
├── .github/workflows/ci.yml       # Automated CI testing and linting
├── app/                           # Next.js 15 App Router terminal client
│   ├── globals.css                # Custom terminal color schemes and scanlines
│   ├── layout.tsx                 # Root layout with font optimization
│   └── page.tsx                   # Main terminal client viewport
├── components/terminal/           # Terminal UI components
│   ├── arbitrage-book.tsx         # Cross-vendor order book with J/K vim navigation
│   ├── command-palette.tsx        # Global ⌘K asset search palette
│   ├── forecast-panel.tsx         # Linear SVG time-series & forecast chart
│   ├── query-console.tsx          # Real-time backend IPC & database diagnostics
│   ├── status-bar.tsx             # Live ticker status and engine health
│   ├── telemetry-panel.tsx        # Landed unit economics & risk haircuts
│   └── ticker.tsx                 # Real-time scrolling arbitrage marquee
├── dags/                          # Airflow DAG orchestration
│   └── mtg_pipeline.py            # Daily pipeline execution schedule
├── lib/                           # Frontend API clients, hooks, and types
│   ├── api-client.ts              # Resilient fetch client with abort controllers
│   ├── hooks.ts                   # SWR data polling and caching hooks
│   ├── series.ts                  # Linear temporal axis interpolation engine
│   └── types.ts                   # Shared TypeScript contracts mirroring Pydantic models
├── src/                           # Backend Python engine
│   ├── analytics/                 # Machine learning & feature store
│   │   ├── backtest.py            # Friction-calibrated backtesting suite
│   │   ├── build_features.py      # Columnar windowing and ASOF joins in DuckDB
│   │   └── train_forecast.py      # Two-stage hurdle XGBoost training pipeline
│   ├── api/                       # REST API layer
│   │   └── main.py                # FastAPI microservice with dependency-injected DuckDB
│   └── etl/                       # Streaming ingestion layer
│       ├── download_raw.py        # Chunked download & decompression
│       ├── extract_prices.py      # Memory-safe ijson lazy stream generator
│       └── load_duckdb.py         # Batch ingestion into fact and dimension tables
├── test/                          # Unit & integration tests
│   └── test_api.py                # API contract, fee schedule, and haircut tests
├── Dockerfile                     # Containerization build configuration
├── requirements.txt               # Locked Python dependencies
└── run_pipeline.py                # CLI pipeline orchestrator
```

---

## Getting Started

### 1. Prerequisites
- **Python 3.10+**
- **Node.js 18+** & **npm**

```bash
# Clone the repository
git clone https://github.com/mglafn/mtg-financial-arbitrage.git
cd mtg-financial-arbitrage

# Set up Python virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Install frontend dependencies
npm install
```

### 2. Run the Full Analytics Pipeline
Execute the automated CLI orchestrator to ingest data, generate features, train the two-stage model, and execute the backtest:

```bash
# Complete end-to-end run
python run_pipeline.py --backtest

# Fast run (re-build features & train without re-downloading raw files)
python run_pipeline.py --analytics-only --backtest
```

### 3. Start Backend & Terminal UI

Start the FastAPI microservice:
```bash
python src/api/main.py
```
- *Interactive API Documentation:* `http://localhost:8000/docs`

Start the Next.js terminal interface:
```bash
npm run dev
```
- *Terminal UI:* `http://localhost:3000`

---

## API Specification

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Diagnostic status of DuckDB connection and loaded model artifacts |
| `GET` | `/api/v1/arbitrage` | Top cross-vendor spreads filtered by `min_spread` and `finish` |
| `GET` | `/api/v1/forecast/{uuid}` | 7-day XGBoost price forecast, landed net payout, and $\kappa_{\text{risk}}$ telemetry |
| `GET` | `/api/v1/card/history/{uuid}` | Historical price observations with rolling `SMA-7` and `SMA-30` |
| `GET` | `/api/v1/card/summary/{uuid}` | Market price distribution, variant count, and active vendor consensus |
| `GET` | `/api/v1/search` | Fast name autocomplete and catalog resolution |
| `GET` | `/api/v1/catalog` | Base asset universe dictionary for client-side resolution |

---

## Unit Testing & Verification

Run the test suite to validate API endpoints, piece-wise fee schedules, dead-zone clamping, and condition risk haircut math:

```bash
pytest test/ -v
```

---

## License
Distributed under the MIT License. See `LICENSE` for more information.
```
