import {
  mockArbitrage,
  mockCatalog,
  mockForecast,
  mockHealth,
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
} from "./types"

// Generic fetcher that catches network failures and seamlessly returns mock data
async function fetchWithFallback<T>(url: string, fallbackFactory: () => T): Promise<T> {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(3500) })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return await res.json()
  } catch {
    // API is offline (e.g. running on Vercel demo mode) -> serve deterministic mock data
    return fallbackFactory()
  }
}

export const apiClient = {
  getHealth: () =>
    fetchWithFallback<HealthCheck & { source: "live" | "mock" }>(
      "/health",
      () => ({ ...mockHealth(), source: "mock" })
    ),

  getArbitrage: (minSpread: number, limit = 100) =>
    fetchWithFallback<ArbitrageOpportunity[]>(
      `/api/v1/arbitrage?min_spread=${minSpread}&limit=${limit}`,
      () => mockArbitrage(minSpread, limit)
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
    fetchWithFallback<{ source: string; cards: CatalogCard[] }>(
      "/api/v1/catalog",
      () => ({ source: "mock", cards: mockCatalog() })
    ),
}