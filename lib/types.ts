// Mirrors the FastAPI Pydantic response schemas exactly.

export interface HealthCheck {
  status: string
  db_connected: boolean
  model_loaded: boolean
}

export interface ArbitrageOpportunity {
  uuid: string
  name?: string
  set_code?: string
  price_date: string
  finish: string
  tcg_price: number
  ck_price: number
  price_spread: number
  spread_pct: number
}

export interface PredictionResponse {
  uuid: string
  vendor: string
  finish: string
  current_price: number
  predicted_7d_price: number
  predicted_gain_pct: number
  model_mae: number
}

export interface CardMarketSummary {
  uuid: string
  latest_price_date: string
  total_market_variants: number
  floor_price: number
  avg_price: number
  ceiling_price: number
  primary_vendor: string
  primary_finish: string
  predicted_7d_price: number
  predicted_gain_pct: number
}

export interface CardSearchResult {
  uuid: string
  name: string
  set_code: string
  finish: string
  floor_price: number
  avg_price: number
  vendor_count: number
}

// Client-only enrichment: names are not part of arbitrage/forecast payloads,
// so the terminal resolves them from the shared catalog.
export interface CatalogCard {
  uuid: string
  name: string
  set_code: string
}
