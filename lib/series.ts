// lib/series.ts
import type { PredictionResponse, PriceHistoryPoint } from './types'

export interface DriftPoint {
  day: number
  date: string
  actual: number | null
  sma7: number | null
  forecast: number | null
  upper: number | null
  lower: number | null
  upper1s: number | null
  lower1s: number | null
  dailyReturnPct: number | null
}

export interface SeriesStats {
  realizedVol: number
  lastClose: number
  driftVol: number
}

const FWD_DAYS = 7

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr.includes('T') ? dateStr : `${dateStr}T12:00:00`)
    return d.toLocaleDateString('en-US', { month: 'short', day: '2-digit' })
  } catch {
    return dateStr
  }
}

function parseToMidnightMs(dateStr: string): number {
  const d = new Date(dateStr.includes('T') ? dateStr : `${dateStr}T12:00:00`)
  return d.getTime()
}

export function buildTimeSeries(
  history: PriceHistoryPoint[],
  forecast: PredictionResponse | null
): { points: DriftPoint[]; stats: SeriesStats } {
  if (!history || history.length === 0) {
    return {
      points: [],
      stats: {
        realizedVol: 0,
        lastClose: 0,
        driftVol: 0,
      },
    }
  }

  const n = history.length
  const lastHistoricalPoint = history[n - 1]
  const anchorTime = parseToMidnightMs(lastHistoricalPoint.price_date)
  const currentPrice = forecast?.current_price ?? lastHistoricalPoint.price
  const ONE_DAY_MS = 24 * 60 * 60 * 1000

  const prices: number[] = history.map((h: PriceHistoryPoint) => h.price)
  const returns: number[] = prices.map((p: number, i: number) => (i === 0 ? 0 : (p - prices[i - 1]) / prices[i - 1]))
  const meanRet = returns.reduce((a: number, b: number) => a + b, 0) / returns.length
  const varRet = returns.reduce((a: number, b: number) => a + (b - meanRet) ** 2, 0) / returns.length
  const dailyVol = Math.sqrt(varRet)
  const realizedVol = dailyVol * Math.sqrt(252) * 100
  const driftVol = dailyVol > 0 ? meanRet / dailyVol : 0

  // 1. Map historical observations
  const points: DriftPoint[] = history.map((pt: PriceHistoryPoint, i: number) => {
    const pointTime = parseToMidnightMs(pt.price_date)
    const day = Math.round((pointTime - anchorTime) / ONE_DAY_MS)
    const isAnchor = day === 0
    const dRet = pt.daily_return_pct ?? (returns[i] * 100)

    return {
      day,
      date: formatDate(pt.price_date),
      actual: pt.price,
      sma7: pt.sma_7 ?? null,
      forecast: isAnchor ? currentPrice : null,
      upper: isAnchor ? currentPrice : null,
      lower: isAnchor ? currentPrice : null,
      upper1s: isAnchor ? currentPrice : null,
      lower1s: isAnchor ? currentPrice : null,
      dailyReturnPct: dRet,
    }
  })

  // 2. Forward forecast trajectory with ±MAE cone
  if (forecast && forecast.predicted_7d_price != null) {
    const target = forecast.predicted_7d_price
    const mae = Math.max(0.01, forecast.model_mae)

    const anchorDate = new Date(
      lastHistoricalPoint.price_date.includes('T')
        ? lastHistoricalPoint.price_date
        : `${lastHistoricalPoint.price_date}T12:00:00`
    )

    for (let k = 1; k <= FWD_DAYS; k++) {
      const fwdDate = new Date(anchorDate)
      fwdDate.setDate(fwdDate.getDate() + k)

      const t = k / FWD_DAYS
      const interpolatedPrice = currentPrice + (target - currentPrice) * t
      const bandOuter = mae * Math.sqrt(k / FWD_DAYS)
      const bandInner = (mae * 0.5) * Math.sqrt(k / FWD_DAYS)

      points.push({
        day: k,
        date: fwdDate.toLocaleDateString('en-US', { month: 'short', day: '2-digit' }),
        actual: null,
        sma7: null,
        forecast: Math.round(interpolatedPrice * 100) / 100,
        upper: Math.round((interpolatedPrice + bandOuter) * 100) / 100,
        lower: Math.max(0.01, Math.round((interpolatedPrice - bandOuter) * 100) / 100),
        upper1s: Math.round((interpolatedPrice + bandInner) * 100) / 100,
        lower1s: Math.max(0.01, Math.round((interpolatedPrice - bandInner) * 100) / 100),
        dailyReturnPct: null,
      })
    }
  }

  return {
    points,
    stats: {
      realizedVol,
      lastClose: currentPrice,
      driftVol,
    },
  }
}