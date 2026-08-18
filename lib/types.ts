/**
 * Shared data contracts mirroring FastAPI Pydantic response models.
 */

export interface HealthCheck {
  status: string
  db_connected: boolean
  model_loaded: boolean
}

export interface CatalogCard {
  uuid: string
  name: string
  set_code: string
  collector_number?: string | null
}

export interface CardVariant {
  uuid: string
  set_code: string
  collector_number?: string | null
  floor_price?: number | null
  edhrec_rank?: number | null
}

export interface PriceHistoryPoint {
  price_date: string
  price: number
  sma_7?: number | null
  sma_30?: number | null
  daily_return_pct?: number | null
}

export interface ArbitrageOpportunity {
  uuid: string
  name?: string
  set_code?: string
  collector_number?: string | null
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
  directional_accuracy_pct?: number | null
  expected_net_payout?: number | null
  net_expected_roi_pct?: number | null
  is_dead_zone_clamped?: boolean | null
  kappa_risk?: number | null
}

export interface CardMarketSummary {
  uuid: string
  name: string
  set_code: string
  collector_number?: string | null
  edhrec_rank?: number | null
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
  collector_number?: string | null
  finish: string
  floor_price: number
  avg_price: number
  vendor_count: number
}