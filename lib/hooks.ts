"use client"

import useSWR from "swr"
import type {
  ArbitrageOpportunity,
  CardMarketSummary,
  CardSearchResult,
  CatalogCard,
  HealthCheck,
  PredictionResponse,
} from "./types"

const fetcher = (url: string) => fetch(url).then((r) => r.json())

export type HealthPayload = HealthCheck & { source: "live" | "mock" }

export function useHealth() {
  return useSWR<HealthPayload>("/api/health", fetcher, { refreshInterval: 8000 })
}

export function useArbitrage(minSpread: number, finish: string) {
  const { data, isLoading, mutate } = useSWR<ArbitrageOpportunity[]>(
    `/api/arbitrage?min_spread=${minSpread}&limit=60`,
    fetcher,
    { refreshInterval: 12000 },
  )
  const rows = (data ?? []).filter((r) => finish === "all" || r.finish === finish)
  return { rows, isLoading, mutate }
}

export function useForecast(uuid: string | null, vendor: string, finish: string) {
  const key = uuid ? `/api/forecast/${uuid}?vendor=${vendor}&finish=${finish}` : null
  return useSWR<PredictionResponse>(key, fetcher)
}

export function useSummary(uuid: string | null) {
  const key = uuid ? `/api/card/summary/${uuid}` : null
  return useSWR<CardMarketSummary>(key, fetcher)
}

export function useSearch(query: string) {
  const key = query.trim().length >= 2 ? `/api/search?name=${encodeURIComponent(query.trim())}` : null
  return useSWR<CardSearchResult[]>(key, fetcher, { keepPreviousData: true })
}

export function useCatalog() {
  const { data } = useSWR<{ source: string; cards: CatalogCard[] }>("/api/catalog", fetcher)
  const map = new Map<string, CatalogCard>()
  for (const c of data?.cards ?? []) map.set(c.uuid, c)
  return map
}
