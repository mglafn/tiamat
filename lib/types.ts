/**
 * lib/types.ts
 * ------------
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
  /** Traded units observed across tracked marketplaces that day. */
  volume?: number | null
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
  /** Order-book depth proxy: number of live listings backing the quote. */
  depth?: number | null
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
  latest_price_date?: string | null
  total_market_variants: number
  floor_price?: number | null
  avg_price?: number | null
  ceiling_price?: number | null
  primary_vendor?: string | null
  primary_finish?: string | null
  predicted_7d_price?: number | null
  predicted_gain_pct?: number | null
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


export interface BacktestSummary {
  total_trades: number
  win_trades: number
  loss_trades: number
  win_rate: number
  total_capital: number
  total_net_profit: number
  portfolio_roi: number
  avg_trade_roi: number
  avg_kelly: number
  profit_factor: number
  test_start_date: string
  test_end_date: string
  test_universe_count: number
}

export interface BacktestAblation {
  naive_trades: number
  naive_win_rate: number
  naive_capital: number
  naive_profit: number
  naive_roi: number
  alpha_cash: number
  alpha_roi_bps: number
  capital_saved: number
  capital_saved_pct: number
  vetoed_losses_avoided: number
}

export interface BacktestTrade {
  uuid: string
  name: string
  set_code: string
  collector_number?: string | null
  finish: string
  price_date: string
  current_price: number
  basis: number
  realized_exit_payout: number
  actual_future_price: number
  pred_magnitude: number
  move_prob: number
  kelly_fraction: number
  allocated_units: number
  total_profit: number
  net_roi_pct: number
  is_win: boolean
  veto_reason?: string | null
}

export interface BacktestEquityPoint {
  date: string
  active_cum_profit: number
  naive_cum_profit: number
}

export interface BacktestResponse {
  status: string
  params: {
    min_net_roi_pct: number
    tau: number
    filter_mode: string
    sort_by: string
    sizing: string
    top_daily: number
    is_pro: boolean
  }
  summary: BacktestSummary
  ablation: BacktestAblation
  equity_curve: BacktestEquityPoint[]
  top_trades: BacktestTrade[]
  worst_trades: BacktestTrade[]
  vetoed_traps: BacktestTrade[]
}