"use client"

import { useMemo, useState } from "react"
import { Crosshair, Loader2, TrendingDown, TrendingUp } from "lucide-react"
import { useForecast, useHistory, useSummary } from "@/lib/hooks"
import { buildTimeSeries, type DriftPoint } from "@/lib/series"
import { usd, pct, shortUuid } from "@/lib/format"

const W = 820
const H = 340
const padL = 52
const padR = 16
const padT = 18
const padB = 26
const FINISHES = ["normal", "foil", "etched"] as const
const VENDORS = ["tcgplayer", "cardkingdom", "starcitygames"] as const

interface ForecastPanelProps {
  uuid: string | null
  selectedFinish: string
  onFinishChange: (finish: string) => void
}

export function ForecastPanel({ uuid, selectedFinish, onFinishChange }: ForecastPanelProps) {
  const [vendor, setVendor] = useState<string>("tcgplayer")
  const finish = selectedFinish
  const setFinish = onFinishChange
  
  const { data: forecast, error: forecastError, isLoading: forecastLoading } = useForecast(uuid, vendor, finish)
  const { data: history = [], error: historyError, isLoading: historyLoading } = useHistory(uuid, vendor, finish, 45)
  const { data: summary, error: summaryError, isLoading: summaryLoading } = useSummary(uuid)
  
  const isLoading = forecastLoading || historyLoading || summaryLoading
  const isError = forecastError || historyError || summaryError

  const points = useMemo<DriftPoint[]>(() => {
    if (!uuid || history.length === 0) return []
    return buildTimeSeries(history, forecast ?? null)
  }, [uuid, history, forecast])

  const geom = useMemo(() => {
    if (points.length === 0) return null
    const vals: number[] = []
    for (const p of points) {
      for (const v of [p.actual, p.sma7, p.sma30, p.forecast, p.upper, p.lower]) {
        if (v != null && !isNaN(v) && v > 0) vals.push(v)
      }
    }
    if (vals.length === 0) return null

    const min = Math.min(...vals)
    const max = Math.max(...vals)
    const pad = (max - min) * 0.14 || max * 0.1
    const lo = Math.max(0.01, min - pad)
    const hi = max + pad
    const plotW = W - padL - padR
    const plotH = H - padT - padB
    
    // Linear time mapping using true day-offsets to prevent axis warping on trading gaps
    const minDay = points[0]?.day ?? 0
    const maxDay = points[points.length - 1]?.day ?? 7
    const daySpan = Math.max(1, maxDay - minDay)

    const x = (day: number) => padL + ((day - minDay) / daySpan) * plotW
    const y = (val: number) => padT + (1 - (val - lo) / Math.max(0.001, hi - lo)) * plotH
    
    const nowX = x(0)

    const line = (key: keyof DriftPoint) =>
      points
        .map((p) => (p[key] == null || isNaN(p[key] as number) ? null : `${x(p.day)},${y(p[key] as number)}`))
        .filter(Boolean)
        .join(" ")

    const upper = points.filter((p) => p.upper != null && !isNaN(p.upper))
    const lower = points.filter((p) => p.lower != null && !isNaN(p.lower))
    let cone = ""
    if (upper.length && lower.length) {
      const up = upper.map((p) => `${x(p.day)},${y(p.upper as number)}`)
      const lowRev = [...lower].reverse().map((p) => `${x(p.day)},${y(p.lower as number)}`)
      cone = `${up.join(" ")} ${lowRev.join(" ")}`
    }

    const ticks = 5
    const yTicks = Array.from({ length: ticks }, (_, i) => {
      const val = lo + ((hi - lo) * i) / (ticks - 1)
      return { val, y: y(val) }
    })

    const xLabels = points
      .filter((_, i) => i % 8 === 0 || points[i].day === 0)
      .map((p) => ({ x: x(p.day), label: p.day === 0 ? "NOW" : p.date, now: p.day === 0 }))

    return { x, y, nowX, line, cone, yTicks, xLabels, minDay, maxDay }
  }, [points])

  const name = summary?.name ?? (uuid ? shortUuid(uuid) : null)
  const gainPositive = (forecast?.predicted_gain_pct ?? 0) >= 0

  return (
    <section className="flex h-full min-h-0 flex-col bg-panel" aria-label="Asset forecast and historical series">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-strong bg-surface px-3 py-1.5">
        <div className="flex items-baseline gap-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-foreground">Asset Forecast</h2>
          {name && (
            <span className="text-[11px] text-accent">
              {name}
              {uuid && <span className="ml-2 text-dim">UUID {shortUuid(uuid)}</span>}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-[10px] uppercase">
          {forecast?.directional_accuracy_pct != null && (
            <span className="hidden text-dim lg:inline">
              Model Acc: <span className="tnum text-foreground font-semibold">{forecast.directional_accuracy_pct}%</span>
            </span>
          )}
          {isError ? (
            <span className="flex items-center gap-1 font-mono text-down">
              FEED OFFLINE
            </span>
          ) : isLoading ? (
            <span className="flex items-center gap-1 font-mono text-accent">
              <Loader2 className="h-3 w-3 animate-spin" /> FETCHING
            </span>
          ) : null}
          <div className="flex overflow-hidden rounded-sm border border-border">
            {VENDORS.map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setVendor(v)}
                className={`px-1.5 py-0.5 transition-colors ${vendor === v ? "bg-surface-2 text-foreground font-semibold" : "text-dim hover:text-muted-foreground"}`}
              >
                {v.slice(0, 3)}
              </button>
            ))}
          </div>
          <div className="flex overflow-hidden rounded-sm border border-border">
            {FINISHES.map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFinish(f)}
                className={`px-1.5 py-0.5 transition-colors ${finish === f ? "bg-accent text-accent-foreground font-semibold" : "text-dim hover:text-muted-foreground"}`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="relative flex min-h-0 flex-1 items-center justify-center p-2">
        {!uuid && (
          <div className="flex flex-col items-center justify-center gap-2 text-center text-dim">
            <Crosshair className="h-8 w-8 text-dim/60" />
            <span className="text-[11px]">Select an asset from the order book or press ⌘K to search</span>
          </div>
        )}
        {uuid && isError && (
          <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-center">
            <span className="font-mono text-[11px] uppercase tracking-wider text-down">Query Error</span>
            <span className="text-[10px] text-dim">Unable to fetch verified time series for this variant</span>
          </div>
        )}
        {uuid && (isLoading || !geom) && !isError && (
          <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent" />
            <span className="font-mono text-[11px] uppercase tracking-wider text-accent">Loading Historical Observations…</span>
            <span className="text-[10px] text-dim">Syncing DuckDB time series and XGBoost inference targets</span>
          </div>
        )}
        {uuid && !isLoading && !isError && geom && (
          <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full max-h-full" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Price history and forecast chart">
            {/* Horizontal Gridlines */}
            {geom.yTicks.map((t, i) => (
              <g key={i}>
                <line x1={padL} y1={t.y} x2={W - padR} y2={t.y} stroke="var(--border)" strokeWidth={0.5} />
                <text x={padL - 6} y={t.y + 3} textAnchor="end" className="fill-dim" fontSize={9}>
                  ${t.val.toFixed(t.val >= 100 ? 0 : 2)}
                </text>
              </g>
            ))}
            {/* Forecast Region Shading */}
            <rect x={geom.nowX} y={padT} width={Math.max(0, W - padR - geom.nowX)} height={H - padT - padB} fill="var(--accent)" opacity={0.04} />
            {/* Uncertainty Cone */}
            {geom.cone && <polygon points={geom.cone} fill="var(--forecast)" opacity={0.16} />}
            {/* SMA-30 Line */}
            <polyline points={geom.line("sma30")} fill="none" stroke="var(--sma30)" strokeWidth={1} strokeDasharray="2 2" />
            {/* SMA-7 Line */}
            <polyline points={geom.line("sma7")} fill="none" stroke="var(--sma7)" strokeWidth={1.25} />
            {/* Historical Close */}
            <polyline points={geom.line("actual")} fill="none" stroke="var(--hist)" strokeWidth={1.5} />
            {/* Forecast Trajectory Line */}
            <polyline points={geom.line("forecast")} fill="none" stroke="var(--forecast)" strokeWidth={2} strokeDasharray="4 3" strokeLinecap="round" />
            {/* NOW Vertical Marker */}
            <line x1={geom.nowX} y1={padT} x2={geom.nowX} y2={H - padB} stroke="var(--border-strong)" strokeWidth={1} strokeDasharray="2 2" />
            {/* 7-Day Target Horizon Point */}
            {forecast && points.length > 0 && (
              <circle cx={geom.x(points[points.length - 1].day)} cy={geom.y(forecast.predicted_7d_price)} r={3.5} fill="var(--forecast)" stroke="var(--background)" strokeWidth={1} />
            )}
            {/* X-axis Labels */}
            {geom.xLabels.map((l, i) => (
              <text key={i} x={l.x} y={H - 8} textAnchor="middle" fontSize={9} className={l.now ? "fill-accent font-semibold" : "fill-dim"}>
                {l.label}
              </text>
            ))}
          </svg>
        )}
      </div>

      {/* Legend & Target Horizon Footer */}
      {forecast && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border bg-surface/50 px-3 py-1.5 text-[10px] uppercase">
          <Legend color="var(--hist)" label="Actual" />
          <Legend color="var(--sma7)" label="SMA-7" />
          <Legend color="var(--sma30)" label="SMA-30" dashed />
          <Legend color="var(--forecast)" label="XGB 7D" dashed />
          <span className="ml-auto flex items-center gap-2">
            <span className="text-dim">7D Target</span>
            <span className="tnum text-forecast font-medium">{usd(forecast.predicted_7d_price)}</span>
            <span className={`tnum flex items-center gap-0.5 font-medium ${gainPositive ? "text-up" : "text-down"}`}>
              {gainPositive ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
              {pct(forecast.predicted_gain_pct)}
            </span>
          </span>
        </div>
      )}
    </section>
  )
}

function Legend({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="inline-block h-0.5 w-4" style={{ background: dashed ? "none" : color, borderTop: dashed ? `1.5px dashed ${color}` : undefined }} />
      <span className="text-muted-foreground">{label}</span>
    </span>
  )
}