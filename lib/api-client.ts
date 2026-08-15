import {
  mockArbitrage,
  mockCatalog,
  mockForecast,
  mockHealth,
  mockHistory,
  mockPrintings,
  mockSearch,
  mockSummary,
} from "./mock-data"
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

async function fetchWithFallback<T>(url: string, fallbackFactory: () => T): Promise<T> {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(4000) })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return await res.json()
  } catch {
    return fallbackFactory()
  }
}

export const apiClient = {
  getHealth: () =>
    fetchWithFallback<HealthCheck & { source: "live" | "mock" }>(
      "/health",
      () => ({ ...mockHealth(), source: "mock" })
    ),

  getArbitrage: (minSpread: number, finish = "all", limit = 100) => {
    const finishParam = finish !== "all" ? `&finish=${encodeURIComponent(finish)}` : ""
    return fetchWithFallback<ArbitrageOpportunity[]>(
      `/api/v1/arbitrage?min_spread=${minSpread}${finishParam}&limit=${limit}`,
      () => mockArbitrage(minSpread, limit)
    )
  },

  getHistory: (uuid: string, vendor = "tcgplayer", finish = "normal", days = 60) =>
    fetchWithFallback<PriceHistoryPoint[]>(
      `/api/v1/card/history/${uuid}?vendor=${encodeURIComponent(vendor)}&finish=${encodeURIComponent(finish)}&days=${days}`,
      () => mockHistory(uuid, days)
    ),

  getForecast: (uuid: string, vendor: string, finish: string) =>
    fetchWithFallback<PredictionResponse | null>(
      `/api/v1/forecast/${uuid}?vendor=${encodeURIComponent(vendor)}&finish=${encodeURIComponent(finish)}`,
      () => mockForecast(uuid, vendor, finish)
    ),

  getSummary: (uuid: string) =>
    fetchWithFallback<CardMarketSummary | null>(
      `/api/v1/card/summary/${uuid}`,
      () => mockSummary(uuid)
    ),

  getPrintings: (uuid: string) =>
    fetchWithFallback<CardVariant[]>(
      `/api/v1/card/printings/${uuid}`,
      () => mockPrintings(uuid)
    ),

  searchCards: (query: string, limit = 20) =>
    fetchWithFallback<CardSearchResult[]>(
      `/api/v1/search?name=${encodeURIComponent(query)}&limit=${limit}`,
      () => mockSearch(query, limit)
    ),

  getCatalog: () =>
    fetchWithFallback<CatalogCard[] | { source: string; cards: CatalogCard[] }>(
      "/api/v1/catalog",
      () => ({ source: "mock", cards: mockCatalog() })
    ),
}