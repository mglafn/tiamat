// lib/hooks.ts
"use client"
import useSWR from "swr"
import type {
  ArbitrageOpportunity,
  CardMarketSummary,
  CardSearchResult,
  CardVariant,
  CatalogCard,
  HealthCheck,
  PredictionResponse,
} from "./types"

const fetcher = async (url: string) => {
  const res = await fetch(url)
  if (!res.ok) throw new Error("Failed to fetch")
  return await res.json()
}

export type HealthPayload = HealthCheck & { source: "live" | "mock" }

export function useHealth() {
  return useSWR<HealthPayload>("/api/health", fetcher, {
    refreshInterval: 10000,
    revalidateOnFocus: false,
    keepPreviousData: true,
  })
}

export function useArbitrage(minSpread: number, finish: string) {
  const { data, error, isLoading, isValidating, mutate } = useSWR<ArbitrageOpportunity[]>(
    `/api/arbitrage?min_spread=${minSpread}&limit=100`,
    fetcher,
    {
      refreshInterval: 20000,
      revalidateOnFocus: false,
      keepPreviousData: true,
      dedupingInterval: 10000,
    },
  )
  const rawRows = data ?? []
  const filtered = rawRows.filter((r) => finish === "all" || r.finish === finish)
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
  const key = uuid ? `/api/forecast/${uuid}?vendor=${vendor}&finish=${finish}` : null
  const { data, error, isLoading, isValidating, mutate } = useSWR<PredictionResponse>(key, fetcher, {
    revalidateOnFocus: false,
    keepPreviousData: false,
    dedupingInterval: 5000,
  })
  return { data, error, isLoading, isValidating, mutate }
}

export function useSummary(uuid: string | null) {
  const key = uuid ? `/api/card/summary/${uuid}` : null
  const { data, error, isLoading, isValidating, mutate } = useSWR<CardMarketSummary>(key, fetcher, {
    revalidateOnFocus: false,
    keepPreviousData: false,
    dedupingInterval: 5000,
  })
  return { data, error, isLoading, isValidating, mutate }
}

export function usePrintings(uuid: string | null) {
  const key = uuid ? `/api/card/printings/${uuid}` : null
  const { data, error, isLoading } = useSWR<CardVariant[]>(key, fetcher, {
    revalidateOnFocus: false,
    keepPreviousData: true,
  })
  return { printings: data ?? [], error, isLoading }
}

export function useSearch(query: string) {
  const key = query.trim().length >= 2 ? `/api/search?name=${encodeURIComponent(query.trim())}` : null
  return useSWR<CardSearchResult[]>(key, fetcher, {
    revalidateOnFocus: false,
    keepPreviousData: true,
  })
}

export function useCatalog() {
  const { data } = useSWR<{ source: string; cards: CatalogCard[] }>("/api/catalog", fetcher, {
    revalidateOnFocus: false,
    keepPreviousData: true,
  })
  const map = new Map<string, CatalogCard>()
  for (const c of data?.cards ?? []) map.set(c.uuid, c)
  return map
}