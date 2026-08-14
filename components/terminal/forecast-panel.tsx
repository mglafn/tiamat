"use client"

import { useMemo, useState } from "react"
import { TrendingDown, TrendingUp } from "lucide-react"
import { useForecast, useSummary, useCatalog } from "@/lib/hooks"
import { buildDrift, type DriftPoint } from "@/lib/series"
import { usd, pct, shortUuid } from "@/lib/format"

const W = 820
const H = 340
const padL = 48
const padR = 14
const padT = 16
const padB = 24

const FINISHES = ["normal", "foil"] as const
const VENDORS = ["tcgplayer", "cardkingdom", "starcitygames"] as const

export function ForecastPanel({ uuid }: { uuid: string | null }) {
  const [finish, setFinish] = useState<string>("normal")
  const [vendor, setVendor] = useState<string>("tcgplayer")
  const { data: forecast, isLoading } = useForecast(uuid, vendor, finish)
  const { data: summary } = useSummary(uuid)
  const catalog = useCatalog()

  const points = useMemo<DriftPoint[]>(() => {
    if (!uuid || !forecast) return []
    return buildDrift(uuid, forecast, summary)
  }, [uuid, forecast, summary])

  const geom = useMemo(() => {
    if (points.length === 0) return null
    const vals: number[] = []
    for (const p of points) {
      for (const v of [p.actual, p.sma7, p.sma30, p.forecast, p.upper, p.lower]) {
        if (v != null) vals.push(v)
      }
    }
    const min = Math.min(...vals)
    const max = Math.max(...vals)
    const pad = (max - min) * 0.12 || max * 0.1
    const lo = min - pad
    const hi = max + pad
    const plotW = W - padL - padR
    const plotH = H - padT - padB
    const n = points.length
    const x = (i: number) => padL + (i / (n - 1)) * plotW
    const y = (val: number) => padT + (1 - (val - lo) / (hi - lo)) * plotH
    const nowIdx = points.findIndex((p) => p.day === 0)

    const line = (key: keyof DriftPoint) =>
      points
        .map((p, i) => (p[key] == null ? null : `${x(i)},${y(p[key] as number)}`))
        .filter(Boolean)
        .join(" ")

    // Uncertainty cone: forward upper then reversed lower, anchored at "now".
    const upper = points.filter((p) => p.upper != null)
    const lower = points.filter((p) => p.lower != null)
    let cone = ""
    if (upper.length) {
      const nowX = x(nowIdx)
      const nowY = y(points[nowIdx].actual as number)
      const up = upper.map((p) => `${x(points.indexOf(p))},${y(p.upper as number)}`)
      const lowRev = [...lower].reverse().map((p) => `${x(points.indexOf(p))},${y(p.lower as number)}`)
      cone = `${nowX},${nowY} ${up.join(" ")} ${lowRev.join(" ")}`
    }

    const ticks = 5
    const yTicks = Array.from({ length: ticks }, (_, i) => {
      const val = lo + ((hi - lo) * i) / (ticks - 1)
      return { val, y: y(val) }
    })

    const xLabels = points
      .filter((_, i) => i % 8 === 0 || points[i].day === 0)
      .map((p) => ({ x: x(points.indexOf(p)), label: p.day === 0 ? "NOW" : p.date, now: p.day === 0 }))

    return { x, y, nowIdx, line, cone, yTicks, xLabels }
  }, [points])

  const name = uuid ? (catalog.get(uuid)?.name ?? shortUuid(uuid)) : null
  const gainPositive = (forecast?.predicted_gain_pct ?? 0) >= 0

  return (
    <section className="flex min-h-0 flex-col bg-panel" aria-label="Asset forecast and historical drift">
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
          <div className="flex overflow-hidden rounded-sm border border-border">
            {VENDORS.map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setVendor(v)}
                className={`px-1.5 py-0.5 transition-colors ${vendor === v ? "bg-surface-2 text-foreground" : "text-dim hover:text-muted-foreground"}`}
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
                className={`px-1.5 py-0.5 transition-colors ${finish === f ? "bg-accent text-accent-foreground" : "text-dim hover:text-muted-foreground"}`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="relative min-h-0 flex-1 p-2">
        {!uuid && <div className="flex h-full items-center justify-center text-[11px] text-dim">Select an asset from the order book</div>}
        {uuid && isLoading && !geom && (
          <div className="flex h-full items-center justify-center text-[11px] text-dim">Running inference…</div>
        )}
        {geom && (
          <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Price drift and forecast chart">
            {/* horizontal gridlines + y labels */}
            {geom.yTicks.map((t, i) => (
              <g key={i}>
                <line x1={padL} y1={t.y} x2={W - padR} y2={t.y} stroke="var(--border)" strokeWidth={0.5} />
                <text x={padL - 6} y={t.y + 3} textAnchor="end" className="fill-dim" fontSize={9}>
                  ${t.val.toFixed(t.val >= 100 ? 0 : 1)}
                </text>
              </g>
            ))}

            {/* forecast region shade */}
            <rect x={geom.x(geom.nowIdx)} y={padT} width={W - padR - geom.x(geom.nowIdx)} height={H - padT - padB} fill="var(--accent)" opacity={0.04} />

            {/* MAE uncertainty cone */}
            {geom.cone && <polygon points={geom.cone} fill="var(--forecast)" opacity={0.16} />}

            {/* SMA-30 */}
            <polyline points={geom.line("sma30")} fill="none" stroke="var(--sma30)" strokeWidth={1} strokeDasharray="1 2" />
            {/* SMA-7 */}
            <polyline points={geom.line("sma7")} fill="none" stroke="var(--sma7)" strokeWidth={1.25} />
            {/* Historical actuals */}
            <polyline points={geom.line("actual")} fill="none" stroke="var(--hist)" strokeWidth={1.5} />
            {/* Forecast */}
            <polyline points={geom.line("forecast")} fill="none" stroke="var(--forecast)" strokeWidth={2} strokeDasharray="4 3" strokeLinecap="round" />

            {/* NOW divider */}
            <line x1={geom.x(geom.nowIdx)} y1={padT} x2={geom.x(geom.nowIdx)} y2={H - padB} stroke="var(--border-strong)" strokeWidth={1} strokeDasharray="2 2" />

            {/* endpoint marker */}
            {forecast && (
              <circle cx={geom.x(points.length - 1)} cy={geom.y(forecast.predicted_7d_price)} r={3} fill="var(--forecast)" stroke="var(--background)" strokeWidth={1} />
            )}

            {/* x labels */}
            {geom.xLabels.map((l, i) => (
              <text key={i} x={l.x} y={H - 8} textAnchor="middle" fontSize={9} className={l.now ? "fill-accent" : "fill-dim"}>
                {l.label}
              </text>
            ))}
          </svg>
        )}
      </div>

      {/* Legend + targets */}
      {forecast && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border bg-surface/50 px-3 py-1.5 text-[10px] uppercase">
          <Legend color="var(--hist)" label="Actual" />
          <Legend color="var(--sma7)" label="SMA-7" />
          <Legend color="var(--sma30)" label="SMA-30" dashed />
          <Legend color="var(--forecast)" label="XGB 7D" dashed />
          <span className="ml-auto flex items-center gap-2">
            <span className="text-dim">7D Target</span>
            <span className="tnum text-forecast">{usd(forecast.predicted_7d_price)}</span>
            <span className={`tnum flex items-center gap-0.5 ${gainPositive ? "text-up" : "text-down"}`}>
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
