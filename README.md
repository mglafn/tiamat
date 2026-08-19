# Secondary Market Trading Terminal & Price Forecasting Pipeline

A quantitative data pipeline, machine learning forecasting service, and trading terminal for secondary market collectible assets (Magic: The Gathering).

The system streams and processes high-cardinality multi-vendor pricing feeds (>1.2GB daily) under a strict 150MB RAM footprint, engineers rolling technical features in DuckDB, and forecasts 7-day price returns using a two-stage hurdle XGBoost model calibrated against real-world fulfillment fees and grading risks.

---

## Key Features & Architecture

- **Streaming ETL (<150MB RAM):** Parses nested JSON files (>1.2GB) using `ijson` chunk generators and batches them into DuckDB columnar storage without exceeding memory constraints.
- **DuckDB Feature Store & ASOF Joins:** Computes rolling moving averages (SMA-7, SMA-30), volatility, and spread velocity using SQL window functions. Uses `ASOF JOIN` to align asynchronous Card Kingdom buylist quotes to preceding TCGplayer retail prices, preventing temporal lookahead bias.
- **Two-Stage Hurdle ML Model:** Solves asset zero-inflation (where over 65% of cards have 0.0% return over 7 days).
  - *Stage 1 (Classifier):* Predicts breakout volatility P(|Return| >= 4.5%) using weighted log-loss.
  - *Stage 2 (Regressor):* Predicts return magnitude strictly on verified movers using L1 loss.
  - *Decision Gate:* Filters out stationary assets unless breakout probability clears a validation-tuned threshold (tau = 0.89).
- **Anti-Leakage Chronological Partitions:** Enforces 14-day calendar embargoes between Train, Validation, and Test splits to match the 7-to-14 day forward target horizon.
- **Fulfillment & Fee Modeling:** 
  - Implements TCGplayer Direct piecewise fee tiers and payment processing drag.
  - Automatically clamps the [$2.50, $2.67] fee cliff dead-zone to $2.49 to optimize net payout.
  - Incorporates condition downgrade risk haircuts (kappa_risk) to model intake grading attrition.
  - Enforces IEEE 754 Banker's Rounding (ROUND_HALF_EVEN) across all ledger calculations.
- **Interactive Trading Terminal:** Next.js 15 interface with linear SVG time-series charting, keyboard navigation (J / K / Space), dynamic fee decomposition waterfall charts, and CSV manifest export.

---

## Model Benchmark & Validation

Evaluated on an out-of-time test partition protected by a 14-day calendar embargo:

- **Model MAE:** 4.0177% (beats naive zero-return baseline of 4.0389% by +2.12 bps)
- **Directional Accuracy:** 66.50% on triggered trade signals
- **Test Set Size:** 476,539 instances

---

## Tech Stack

- **Data & ETL:** Python 3.10+, `ijson`, DuckDB, Pandas, NumPy, Apache Airflow
- **Machine Learning:** XGBoost, Scikit-Learn, Joblib
- **Backend API:** FastAPI, Uvicorn, Pydantic v2
- **Frontend Terminal:** Next.js 15 (App Router), React 19, Tailwind CSS, SWR, Lucide Icons
- **Testing & Quality:** PyTest, Black, GitHub Actions CI

---

## Project Structure

├── app/ # Next.js 15 terminal client ├── components/terminal/ # UI panels
(Spread book, forecast chart, telemetry) ├── dags/ # Airflow DAG for daily
pipeline execution ├── lib/ # API client, unit economics engine, types ├── src/
│ ├── analytics/ # Feature engineering, XGBoost training, backtesting │ ├──
api/ # FastAPI REST endpoints and fee logic │ └── etl/ # ijson streaming
extractor and DuckDB loader ├── test/ # PyTest suite for API and rate card math
├── run_pipeline.py # Unified CLI pipeline orchestrator └── requirements.txt #
Locked Python dependencies


---

## Getting Started

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/mglafn/mtg-trading-terminal.git
cd mtg-trading-terminal

# Setup Python virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Install frontend dependencies
npm install

2. Run the Data & Training Pipeline

# Full end-to-end run (ETL, feature build, model training, and backtest)
python run_pipeline.py --backtest

# Fast run (re-build features & train without re-downloading raw files)
python run_pipeline.py --analytics-only --backtest

3. Start Backend & Terminal

Start the FastAPI microservice on port 8000:

python src/api/main.py

Start the Next.js terminal on port 3000:

npm run dev

API Reference

  - GET /health - Engine diagnostics and model status
  - GET /api/v1/arbitrage - Top multi-vendor price spreads filtered by minimum
    spread and finish
  - GET /api/v1/forecast/{uuid} - 7-day XGBoost price forecast, net payout, and
    condition risk haircut
  - GET /api/v1/card/history/{uuid} - Historical price observations with rolling
    SMA-7 and SMA-30
  - GET /api/v1/card/summary/{uuid} - High-level market statistics, variant
    counts, and vendor consensus
  - GET /api/v1/search - Autocomplete card name resolution across catalog
  - GET /api/v1/catalog - Core asset dictionary for client-side resolution

Testing

Run the test suite to validate API endpoints, piecewise rate card math,
dead-zone clamping, and risk haircuts:

pytest test/ -v

License

MIT License.

