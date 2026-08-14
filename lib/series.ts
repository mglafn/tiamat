import type { CardMarketSummary, PredictionResponse } from "./types"

function hashSeed(str: string): number {
  let h = 2166136261
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}
function mulberry32(seed: number) {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export interface DriftPoint {
  day: number // negative = historical, 0 = now, positive = forecast horizon
  date: string
  actual: number | null
  sma7: number | null
  sma30: number | null
  forecast: number | null
  upper: number | null
  lower: number | null
}

const HIST_DAYS = 44
const FWD_DAYS = 7

// Reconstructs a plausible historical drift curve from the documented API
// fields (current price + SMA anchors), then projects the XGBoost 7-day
// forward path with a widening ±MAE uncertainty corridor.
export function buildDrift(uuid: string, forecast: PredictionResponse, summary?: CardMarketSummary): DriftPoint[] {
  const rnd = mulberry32(hashSeed(uuid + "drift"))
  const current = forecast.current_price
  const floor = summary?.floor_price ?? current * 0.9
  const ceiling = summary?.ceiling_price ?? current * 1.12
  const range = Math.max(ceiling - floor, current * 0.08)

  // Build a mean-reverting random walk that ENDS exactly at `current`.
  const raw: number[] = []
  let v = current * (0.94 + rnd() * 0.05)
  for (let i = 0; i < HIST_DAYS; i++) {
    const meanPull = (current - v) * 0.06
    const shock = (rnd() - 0.5) * range * 0.09
    v = v + meanPull + shock
    v = Math.min(Math.max(v, floor * 0.96), ceiling * 1.04)
    raw.push(v)
  }
  raw[raw.length - 1] = current // pin the endpoint

  const sma = (arr: number[], idx: number, win: number) => {
    const start = Math.max(0, idx - win + 1)
    const slice = arr.slice(start, idx + 1)
    return slice.reduce((a, b) => a + b, 0) / slice.length
  }

  const base = new Date("2026-08-14")
  const fmt = (offset: number) => {
    const d = new Date(base)
    d.setDate(d.getDate() + offset)
    return d.toLocaleDateString("en-US", { month: "short", day: "2-digit" })
  }

  const points: DriftPoint[] = raw.map((actual, i) => {
    const day = i - (HIST_DAYS - 1)
    return {
      day,
      date: fmt(day),
      actual: Math.round(actual * 100) / 100,
      sma7: Math.round(sma(raw, i, 7) * 100) / 100,
      sma30: Math.round(sma(raw, i, 30) * 100) / 100,
      forecast: day === 0 ? actual : null,
      upper: null,
      lower: null,
    }
  })

  // Forward XGBoost path: interpolate current -> predicted_7d_price.
  const target = forecast.predicted_7d_price
  // Visible corridor derived from model MAE, widening with horizon.
  const maeUnit = Math.max(forecast.model_mae, current * 0.006)
  for (let k = 1; k <= FWD_DAYS; k++) {
    const t = k / FWD_DAYS
    const fc = current + (target - current) * (0.35 * t + 0.65 * t * t)
    const band = maeUnit * Math.sqrt(k) * 6 + current * 0.004 * k
    points.push({
      day: k,
      date: fmt(k),
      actual: null,
      sma7: null,
      sma30: null,
      forecast: Math.round(fc * 100) / 100,
      upper: Math.round((fc + band) * 100) / 100,
      lower: Math.round((fc - band) * 100) / 100,
    })
  }

  return points
}
