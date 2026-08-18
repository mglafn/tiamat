/**
 * HTTP client for the FastAPI backend.
 * Handles timeouts via AbortController and surfaces HTTP status errors to SWR.
 */

import type {
  ArbitrageOpportunity,
  CardMarketSummary,
  CardSearchResult,
  CardVariant,
  CatalogCard,
  HealthCheck,
  PredictionResponse,
  PriceHistoryPoint,
} from "./types"

const REQUEST_TIMEOUT_MS = 6000

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public body: string
  ) {
    super(`API Error ${status} (${statusText}): ${body}`)
    this.name = "ApiError"
  }
}

async function apiFetch<T>(url: string): Promise<T> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  try {
    const res = await fetch(url, { signal: controller.signal })
    if (!res.ok) {
      const errorBody = await res.text().catch(() => "Unknown error")
      throw new ApiError(res.status, res.statusText, errorBody)
    }
    return (await res.json()) as T
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(`Request to '${url}' timed out after ${REQUEST_TIMEOUT_MS}ms`)
    }
    throw err
  } finally {
    clearTimeout(timeoutId)
  }
}

export const apiClient = {
  /**
   * Health and diagnostic check. Falls back gracefully when the server is offline.
   */
  getHealth: async (): Promise<HealthCheck & { source: "live" | "mock" }> => {
    try {
      const data = await apiFetch<HealthCheck>("/health")
      return { ...data, source: "live" }
    } catch {
      return { status: "offline", db_connected: false, model_loaded: false, source: "mock" }
    }
  },

  /**
   * Returns top cross-vendor arbitrage spreads with optional finish filter.
   */
  getArbitrage: (minSpread: number, finish = "all", limit = 100) => {
    const finishParam = finish !== "all" ? `&finish=${encodeURIComponent(finish)}` : ""
    return apiFetch<ArbitrageOpportunity[]>(
      `/api/v1/arbitrage?min_spread=${minSpread}${finishParam}&limit=${limit}`
    )
  },

  /**
   * Historical price observations and rolling moving averages for a card.
   */
  getHistory: (uuid: string, vendor = "tcgplayer", finish = "normal", days = 60) =>
    apiFetch<PriceHistoryPoint[]>(
      `/api/v1/card/history/${encodeURIComponent(uuid)}?finish=${encodeURIComponent(finish)}&days=${days}`
    ),

  /**
   * Forward 7-day price forecast and condition-adjusted payout metrics.
   */
  getForecast: (uuid: string, vendor = "tcgplayer", finish = "normal") =>
    apiFetch<PredictionResponse>(
      `/api/v1/forecast/${encodeURIComponent(uuid)}?finish=${encodeURIComponent(finish)}`
    ),

  /**
   * Aggregate market statistics across available vendors for a card SKU.
   */
  getSummary: (uuid: string) =>
    apiFetch<CardMarketSummary>(
      `/api/v1/card/summary/${encodeURIComponent(uuid)}`
    ),

  /**
   * All physical printings and sets associated with a card name.
   */
  getPrintings: (uuid: string) =>
    apiFetch<CardVariant[]>(
      `/api/v1/card/printings/${encodeURIComponent(uuid)}`
    ),

  /**
   * Autocomplete/search against card names in dim_cards.
   */
  searchCards: (query: string, limit = 20) =>
    apiFetch<CardSearchResult[]>(
      `/api/v1/search?name=${encodeURIComponent(query)}&limit=${limit}`
    ),

  /**
   * Core catalog mappings for fast in-memory client resolution.
   */
  getCatalog: () =>
    apiFetch<CatalogCard[]>("/api/v1/catalog"),
}