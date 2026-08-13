# Enterprise Financial Arbitrage & Asset Forecasting Engine

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![DuckDB](https://img.shields.io/badge/DuckDB-In--Memory%20Analytics-yellow.svg)](https://duckdb.org/)
[![XGBoost](https://img.shields.io/badge/XGBoost-Time--Series%20Forecasting-green.svg)](https://xgboost.ai/)
[![FastAPI](https://img.shields.io/badge/FastAPI-REST%20Microservice-009688.svg)](https://fastapi.tiangolo.com/)

An end-to-end analytical pipeline and RESTful microservice built to detect cross-vendor price arbitrage and forecast 7-day forward asset valuations across secondary financial market data. 

Engineered to handle high-volume, deeply nested JSON payloads (>1.2GB) with near-zero memory footprint using memory-mapped streaming ETL, DuckDB analytical windowing, and XGBoost gradient boosting.

---

## 💡 System Architecture

```
┌─────────────────────────┐
│ MTGJSON Pricing Feed   │
│ (1.2GB Compressed JSON) │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐      Lazy Stream      ┌─────────────────────────┐
│ Memory-Efficient ETL    ├──────────────────────►│ DuckDB Analytical Engine│
│ (ijson + Pandas)        │  Batch Ingestion      │ (fact_prices)           │
└─────────────────────────┘                       └────────────┬────────────┘
                                                               │
                                                               ▼
┌─────────────────────────┐   Window Functions    ┌─────────────────────────┐
│ FastAPI Microservice    │◄──────────────────────┤ Feature Engineering &   │
│ (Arbitrage & Inference) │   Model Predictions   │ ML Dataset Generation   │
└─────────────────────────┘                       └─────────────────────────┘
```

---

## 🛠️ Tech Stack & Key Design Decisions

* **Streaming Extraction (`ijson`):** Lazily parses 1.2GB+ nested JSON structures without loading the full payload into RAM, keeping peak memory usage under **150MB**.
* **Analytical Data Warehouse (`DuckDB`):** Executes high-performance SQL window functions (`LAG`, `LEAD`, `AVG OVER`) directly on persistent columnar storage to generate 7-day/30-day Simple Moving Averages (SMA), daily returns, and cross-vendor spreads.
* **Predictive Modeling (`XGBoost`):** Out-of-time split (80/20 time-series split) trained on historical price indicators to predict 7-day forward asset movements.
* **Microservice Layer (`FastAPI`):** Asynchronous REST API serving low-latency arbitrage queries and real-time model inference.

---

## 🚀 Getting Started

### 1. Prerequisites
Ensure you have Python 3.10+ installed.

```bash
git clone https://github.com/mglafn/mtg-financial-arbitrage.git
cd mtg-financial-arbitrage
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Execution Pipeline

#### Step A: Download & Ingest Raw Data
Downloads the compressed MTGJSON price payload, decompresses it in memory-safe chunks, and ingests flattened records into DuckDB.
```bash
python src/etl/download_raw.py
python src/etl/load_duckdb.py
```

#### Step B: Feature Engineering & Indicator Calculation
Executes SQL windowing scripts to generate rolling SMAs, daily returns, and cross-vendor arbitrage spreads.
```bash
python src/analytics/build_features.py
```

#### Step C: Train XGBoost Forecasting Model
Trains the gradient boosting model on historical price points and persists model artifacts.
```bash
python src/analytics/train_forecast.py
```

#### Step D: Spin Up FastAPI Microservice
Starts the local API server.
```bash
python src/api/main.py
```
* Access Interactive API Docs (Swagger UI): `http://localhost:8000/docs`

---

## 📊 API Endpoint Overview

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Health check verifying DuckDB connection and model load state |
| `GET` | `/api/v1/arbitrage` | Returns top cross-vendor price spread opportunities (filtering by `min_spread`) |
| `GET` | `/api/v1/forecast/{uuid}` | Serves 7-day forward XGBoost price predictions for a specific asset |

---

## 📝 License
Distributed under the MIT License.