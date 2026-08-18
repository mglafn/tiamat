
# MTG Financial Arbitrage & Price Forecasting Engine

An analytical pipeline, REST microservice, and trading terminal designed to detect cross-vendor price arbitrage and forecast 7-day forward returns for secondary Magic: The Gathering singles.

Processes the MTGJSON pricing feed (>1.2GB) with a sub-150MB memory footprint using streaming ETL (`ijson`), columnar windowing in DuckDB, and a two-stage hurdle XGBoost forecasting model.

---

## Architecture Overview

```
[MTGJSON Feed] ──(Streaming ijson)──► [DuckDB: fact_prices]
                                             │
                                     (Window Functions & ASOF Joins)
                                             │
                                             ▼
                                   [DuckDB Feature Store]
                                   ├── fact_card_features
                                   ├── fact_training_dataset
                                   └── fact_arbitrage_opportunities
                                             │
                                      (XGBoost Model)
                                             │
                                             ▼
                                  [FastAPI Microservice] ──► [Next.js Terminal]
```

---

## Key Design Decisions

- **Memory-Safe Extraction (`ijson`):** Lazily streams nested JSON pricing records into DuckDB in fixed-size batches, avoiding full memory allocation of the 1.2GB payload.
- **Analytical Storage (`DuckDB`):** Executes rolling technical indicators (`SMA-7`, `SMA-30`, volatility, spread velocity) and temporal `ASOF` joins directly in columnar storage.
- **Two-Stage Hurdle Model (`XGBoost`):** 
  - *Stage 1:* Binary classifier predicting breakout catalyst probability ($P(|\Delta| \ge 4.5\%)$).
  - *Stage 2:* Conditional regressor estimating magnitude on movers using L1 loss.
  - Probability decision thresholds ($\tau$) are tuned strictly on validation splits with 14-day anti-leakage embargoes.
- **Friction-Calibrated Unit Economics:** Implements exact TCGplayer Direct rate cards, Banker's rounding (`ROUND_HALF_EVEN`), dead-band price clamping ($2.50 to $2.67), Card Kingdom store credit math (+30%), and condition downgrade risk adjustments ($\kappa_{\text{risk}}$).

---

## Quickstart

### 1. Prerequisites
Python 3.10+ and Node.js 18+

```bash
git clone https://github.com/mglafn/mtg-financial-arbitrage.git
cd mtg-financial-arbitrage
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
npm install
```

### 2. Run the End-to-End Pipeline

Run the automated orchestrator to download raw data, build features, and train the model:

```bash
python run_pipeline.py
```

Optional flags:
- `--analytics-only`: Re-run feature store generation and training without downloading raw data.
- `--backtest`: Execute the out-of-time backtest suite after training.
- `--hurdle 10.0`: Specify minimum expected net ROI hurdle percentage for the backtest.

### 3. Start Backend & Terminal

Start the FastAPI microservice:
```bash
python src/api/main.py
```
* Interactive API docs: `http://localhost:8000/docs`

Start the frontend terminal client:
```bash
npm run dev
```
* Terminal UI: `http://localhost:3000`

---

## API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Diagnostic status of DuckDB connection and model loading |
| `GET` | `/api/v1/arbitrage` | Top cross-vendor spreads filtered by `min_spread` and `finish` |
| `GET` | `/api/v1/forecast/{uuid}` | 7-day XGBoost price prediction and condition-adjusted net payout |
| `GET` | `/api/v1/card/history/{uuid}` | Verified price observations with rolling SMAs |
| `GET` | `/api/v1/card/summary/{uuid}` | Market price distribution and vendor overview |
| `GET` | `/api/v1/search` | Name autocomplete and catalog resolution |

---

## License
MIT
