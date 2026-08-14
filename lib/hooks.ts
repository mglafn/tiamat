// lib/hooks.ts
"use client"
import useSWR from "swr"
import { apiClient } from "./api-client"
import type {
  ArbitrageOpportunity,
  CardMarketSummary,
  CardSearchResult,
  CardVariant,
  CatalogCard,
  HealthCheck,
  PredictionResponse,
} from "./types"

export type HealthPayload = HealthCheck & { source: "live" | "mock" }

export function useHealth() {
  return useSWR<HealthPayload>("health-status", () => apiClient.getHealth(), {
    refreshInterval: 10000,
    revalidateOnFocus: false,
    keepPreviousData: true,
  })
}

export function useArbitrage(minSpread: number, finish: string) {
  const { data, error, isLoading, isValidating, mutate } = useSWR<ArbitrageOpportunity[]>(
    [`arbitrage-book`, minSpread],
    () => apiClient.getArbitrage(minSpread),
    {
      refreshInterval: 20000,
      revalidateOnFocus: false,
      keepPreviousData: true,
      dedupingInterval: 10000,
    }
  )

  const rawRows: ArbitrageOpportunity[] = data ?? []
  const filtered = rawRows.filter((r: ArbitrageOpportunity) => finish === "all" || r.finish === finish)
  const seen = new Set<string>()
  const rows: ArbitrageOpportunity[] = []
  
  for (const r of filtered) {
    const key = `${r.uuid}-${r.finish}`
    if (!seen.has(key)) {
      seen.add(key)
      rows.push(r)
    }
  }

  return { rows, error, isLoading, isValidating, mutate }
}

export function useForecast(uuid: string | null, vendor: string, finish: string) {
  return useSWR<PredictionResponse | null>(
    uuid ? [`forecast`, uuid, vendor, finish] : null,
    () => (uuid ? apiClient.getForecast(uuid, vendor, finish) : null),
    {
      revalidateOnFocus: false,
      keepPreviousData: false,
      dedupingInterval: 5000,
    }
  )
}

export function useSummary(uuid: string | null) {
  return useSWR<CardMarketSummary | null>(
    uuid ? [`summary`, uuid] : null,
    () => (uuid ? apiClient.getSummary(uuid) : null),
    {
      revalidateOnFocus: false,
      keepPreviousData: false,
      dedupingInterval: 5000,
    }
  )
}

export function usePrintings(uuid: string | null) {
  const { data, error, isLoading } = useSWR<CardVariant[]>(
    uuid ? [`printings`, uuid] : null,
    () => (uuid ? apiClient.getPrintings(uuid) : []),
    {
      revalidateOnFocus: false,
      keepPreviousData: true,
    }
  )
  return { printings: data ?? [], error, isLoading }
}

export function useSearch(query: string) {
  return useSWR<CardSearchResult[]>(
    query.trim().length >= 2 ? [`search`, query.trim()] : null,
    () => apiClient.searchCards(query.trim()),
    {
      revalidateOnFocus: false,
      keepPreviousData: true,
    }
  )
}

export function useCatalog() {
  const { data } = useSWR<{ source: string; cards: CatalogCard[] }>("catalog-map", () => apiClient.getCatalog(), {
    revalidateOnFocus: false,
    keepPreviousData: true,
  })
  
  const map = new Map<string, CatalogCard>()
  for (const c of data?.cards ?? []) map.set(c.uuid, c)
  return map
}