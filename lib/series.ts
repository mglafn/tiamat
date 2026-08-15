// lib/series.ts
import type { PredictionResponse, PriceHistoryPoint } from "./types"

export interface DriftPoint {
  day: number // negative = historical, 0 = latest verified close, positive = forecast horizon
  date: string
  actual: number | null
  sma7: number | null
  sma30: number | null
  forecast: number | null
  upper: number | null
  lower: number | null
}

const FWD_DAYS = 7

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr.includes("T") ? dateStr : `${dateStr}T12:00:00`)
    return d.toLocaleDateString("en-US", { month: "short", day: "2-digit" })
  } catch {
    return dateStr
  }
}

function parseToMidnightMs(dateStr: string): number {
  const d = new Date(dateStr.includes("T") ? dateStr : `${dateStr}T12:00:00`)
  return d.getTime()
}

/**
 * Combines verified DuckDB historical pricing with XGBoost forward projections.
 * Accurately aligns dates to avoid non-linear axis warping on missing trading days.
 */
export function buildTimeSeries(
  history: PriceHistoryPoint[],
  forecast: PredictionResponse | null
): DriftPoint[] {
  if (!history || history.length === 0) {
    return []
  }

  const n = history.length
  const lastHistoricalPoint = history[n - 1]
  const anchorTime = parseToMidnightMs(lastHistoricalPoint.price_date)
  const currentPrice = forecast?.current_price ?? lastHistoricalPoint.price
  const ONE_DAY_MS = 24 * 60 * 60 * 1000

  // 1. Map verified historical observations with true day-offset calculation
  const points: DriftPoint[] = history.map((pt) => {
    const pointTime = parseToMidnightMs(pt.price_date)
    const day = Math.round((pointTime - anchorTime) / ONE_DAY_MS)
    const isAnchor = day === 0

    return {
      day,
      date: formatDate(pt.price_date),
      actual: pt.price,
      sma7: pt.sma_7 ?? null,
      sma30: pt.sma_30 ?? null,
      forecast: isAnchor ? currentPrice : null,
      upper: isAnchor ? currentPrice : null,
      lower: isAnchor ? currentPrice : null,
    }
  })

  // 2. Map forward forecast trajectory if prediction artifact exists
  if (forecast && forecast.predicted_7d_price != null) {
    const target = forecast.predicted_7d_price
    const mae = Math.max(0.01, forecast.model_mae)
    
    const anchorDate = new Date(
      lastHistoricalPoint.price_date.includes("T") 
        ? lastHistoricalPoint.price_date 
        : `${lastHistoricalPoint.price_date}T12:00:00`
    )

    for (let k = 1; k <= FWD_DAYS; k++) {
      const fwdDate = new Date(anchorDate)
      fwdDate.setDate(fwdDate.getDate() + k)

      const t = k / FWD_DAYS
      const interpolatedPrice = currentPrice + (target - currentPrice) * t
      const uncertaintyBand = mae * Math.sqrt(k / FWD_DAYS)

      points.push({
        day: k,
        date: fwdDate.toLocaleDateString("en-US", { month: "short", day: "2-digit" }),
        actual: null,
        sma7: null,
        sma30: null,
        forecast: Math.round(interpolatedPrice * 100) / 100,
        upper: Math.round((interpolatedPrice + uncertaintyBand) * 100) / 100,
        lower: Math.max(0.01, Math.round((interpolatedPrice - uncertaintyBand) * 100) / 100),
      })
    }
  }

  return points
}