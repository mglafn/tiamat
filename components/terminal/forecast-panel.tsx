'use client'

import { useMemo, useState } from 'react'
import { Activity, BarChart2, Check, TrendingUp } from 'lucide-react'
import { useForecast, useHistory, useSummary } from '@/lib/hooks'
import { buildTimeSeries, type DriftPoint } from '@/lib/series'
import { usd, pct, shortUuid } from '@/lib/format'
import { SetSelector } from './set-selector'

interface ForecastPanelProps {
  uuid: string | null
  selectedFinish: string
  onFinishChange: (finish: string) => void
  onSelectUuid?: (uuid: string) => void
}

export function ForecastPanel({
  uuid,
  selectedFinish,
  onFinishChange,
  onSelectUuid,
}: ForecastPanelProps) {
  const { data: summary } = useSummary(uuid)
  const { data: history = [] } = useHistory(uuid, 'tcgplayer', selectedFinish, 60)
  const { data: forecast } = useForecast(uuid, 'tcgplayer', selectedFinish)

  const [mode, setMode] = useState<'nominal' | 'risk-adj'>('nominal')
  const [showBands, setShowBands] = useState(true)
  const [showVpvr, setShowVpvr] = useState(false)
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)

  const name = summary?.name ?? (uuid ? shortUuid(uuid) : 'Select Asset')
  const setCode = summary?.set_code ?? '—'
  const collectorNum = summary?.collector_number

  const { points, stats } = useMemo(() => {
    return buildTimeSeries(history, forecast)
  }, [history, forecast])

  // Chart dimensions and scales
  const chartW = 740
  const chartH = 340
  const padL = 48
  const padR = showVpvr ? 80 : 36
  const padT = 24
  const padB = 70
  const plotW = chartW - padL - padR
  const plotH = chartH - padT - padB

  const allPrices = useMemo(() => {
    const vals: number[] = []
    points.forEach((p) => {
      if (p.actual != null) vals.push(p.actual)
      if (p.sma7 != null) vals.push(p.sma7)
      if (p.sma30 != null) vals.push(p.sma30)
      if (p.upper != null) vals.push(p.upper)
      if (p.lower != null) vals.push(p.lower)
      if (p.bollUpper != null) vals.push(p.bollUpper)
      if (p.bollLower != null) vals.push(p.bollLower)
    })
    return vals.length > 0 ? vals : [1, 10]
  }, [points])

  const minP = Math.min(...allPrices) * 0.96
  const maxP = Math.max(...allPrices) * 1.04
  const priceRange = Math.max(0.01, maxP - minP)

  const n = points.length
  const toX = (i: number) => padL + (i / Math.max(1, n - 1)) * plotW
  const toY = (price: number) => padT + plotH - ((price - minP) / priceRange) * plotH

  // Path generators
  const actualPath = useMemo(() => {
    return points
      .map((p, i) => {
        const val = mode === 'risk-adj' && p.riskAdj != null ? p.riskAdj : p.actual
        return val != null ? `${i === 0 ? 'M' : 'L'} ${toX(i).toFixed(1)} ${toY(val).toFixed(1)}` : ''
      })
      .filter(Boolean)
      .join(' ')
  }, [points, mode, minP, priceRange])

  const sma7Path = useMemo(() => {
    return points
      .map((p, i) => (p.sma7 != null ? `${p.sma7 ? 'L' : 'M'} ${toX(i).toFixed(1)} ${toY(p.sma7).toFixed(1)}` : ''))
      .filter(Boolean)
      .join(' ')
      .replace(/^L/, 'M')
  }, [points, minP, priceRange])

  const sma30Path = useMemo(() => {
    return points
      .map((p, i) => (p.sma30 != null ? `${p.sma30 ? 'L' : 'M'} ${toX(i).toFixed(1)} ${toY(p.sma30).toFixed(1)}` : ''))
      .filter(Boolean)
      .join(' ')
      .replace(/^L/, 'M')
  }, [points, minP, priceRange])

  // Forecast Cones (2σ and 1σ)
  const forecastFan2s = useMemo(() => {
    const fwd = points.filter((p) => p.day >= 0 && p.upper != null && p.lower != null)
    if (fwd.length < 2) return ''
    const upperPts = fwd.map((p) => {
      const idx = points.indexOf(p)
      return `${toX(idx).toFixed(1)},${toY(p.upper!).toFixed(1)}`
    })
    const lowerPts = fwd
      .slice()
      .reverse()
      .map((p) => {
        const idx = points.indexOf(p)
        return `${toX(idx).toFixed(1)},${toY(p.lower!).toFixed(1)}`
      })
    return `M ${upperPts.join(' L ')} L ${lowerPts.join(' L ')} Z`
  }, [points, minP, priceRange])

  const forecastFan1s = useMemo(() => {
    const fwd = points.filter((p) => p.day >= 0 && p.upper1s != null && p.lower1s != null)
    if (fwd.length < 2) return ''
    const upperPts = fwd.map((p) => {
      const idx = points.indexOf(p)
      return `${toX(idx).toFixed(1)},${toY(p.upper1s!).toFixed(1)}`
    })
    const lowerPts = fwd
      .slice()
      .reverse()
      .map((p) => {
        const idx = points.indexOf(p)
        return `${toX(idx).toFixed(1)},${toY(p.lower1s!).toFixed(1)}`
      })
    return `M ${upperPts.join(' L ')} L ${lowerPts.join(' L ')} Z`
  }, [points, minP, priceRange])

  const forecastLine = useMemo(() => {
    const fwd = points.filter((p) => p.day >= 0 && p.forecast != null)
    return fwd
      .map((p, i) => {
        const idx = points.indexOf(p)
        return `${i === 0 ? 'M' : 'L'} ${toX(idx).toFixed(1)} ${toY(p.forecast!).toFixed(1)}`
      })
      .join(' ')
  }, [points, minP, priceRange])

  // Active hover point
  const activePoint: DriftPoint | null = hoveredIndex !== null ? points[hoveredIndex] ?? null : points[points.length - 1] ?? null
  const activeIdx = hoveredIndex !== null ? hoveredIndex : points.length - 1

  return (
    <section className="flex h-full min-h-0 flex-col bg-panel" aria-label="Asset forecast and temporal pricing">
      {/* 1. Header Toolbar with integrated SetSelector */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-strong bg-surface px-3 py-1.5">
        <div className="flex min-w-0 items-center gap-2">
          <TrendingUp className="h-3.5 w-3.5 text-accent shrink-0" />
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-foreground shrink-0">
            Asset Forecast
          </h2>
          <span className="text-border-strong">|</span>
          <span className="truncate font-mono text-[12px] font-bold text-accent">
            {name}
          </span>

          {/* Integrated Set / Printing Popover */}
          {uuid && onSelectUuid && (
            <SetSelector
              uuid={uuid}
              currentSetCode={setCode}
              currentCollectorNumber={collectorNum}
              onSelectUuid={onSelectUuid}
            />
          )}

          {uuid && (
            <span className="hidden font-mono text-[10px] text-dim sm:inline">
              UUID {shortUuid(uuid)}
            </span>
          )}
        </div>

        {/* View Mode & Finish Controls */}
        <div className="flex items-center gap-2">
          <div className="flex overflow-hidden rounded-sm border border-border text-[9.5px] font-mono">
            <button
              type="button"
              onClick={() => setMode('nominal')}
              className={`px-1.5 py-0.5 transition-colors ${
                mode === 'nominal' ? 'bg-surface-3 font-bold text-foreground' : 'text-dim hover:text-muted-foreground'
              }`}
            >
              nominal
            </button>
            <button
              type="button"
              onClick={() => setMode('risk-adj')}
              className={`px-1.5 py-0.5 transition-colors ${
                mode === 'risk-adj' ? 'bg-surface-3 font-bold text-accent' : 'text-dim hover:text-muted-foreground'
              }`}
            >
              risk-adj
            </button>
          </div>

          <button
            type="button"
            onClick={() => setShowBands((b) => !b)}
            className={`rounded-sm border px-1.5 py-0.5 font-mono text-[9.5px] transition-colors ${
              showBands ? 'border-accent/40 bg-accent/10 text-accent' : 'border-border text-dim hover:text-foreground'
            }`}
          >
            2σ bands
          </button>

          <button
            type="button"
            onClick={() => setShowVpvr((v) => !v)}
            className={`flex items-center gap-1 rounded-sm border px-1.5 py-0.5 font-mono text-[9.5px] transition-colors ${
              showVpvr ? 'border-accent/40 bg-accent/10 text-accent' : 'border-border text-dim hover:text-foreground'
            }`}
          >
            <BarChart2 className="h-2.5 w-2.5" />
            <span>VPVR</span>
          </button>

          <div className="flex overflow-hidden rounded-sm border border-border text-[9.5px] font-mono">
            {(['normal', 'foil', 'etched'] as const).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => onFinishChange(f)}
                className={`px-1.5 py-0.5 uppercase transition-colors ${
                  selectedFinish === f
                    ? 'bg-accent font-bold text-accent-foreground'
                    : 'text-dim hover:bg-surface-2 hover:text-muted-foreground'
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 2. Top Rolling Statistics Strip */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b border-border bg-surface/40 px-3 py-1 font-mono text-[10px] text-dim">
        <span>
          Realized Vol (Ann.): <strong className="text-foreground">{stats.realizedVol.toFixed(1)}%</strong>
        </span>
        <span>
          Drift: <strong className={stats.driftVol >= 0 ? 'text-up' : 'text-down'}>{stats.driftVol.toFixed(2)}</strong>
        </span>
        <span>
          Historical Range: <strong className={stats.changeFromFirstPct >= 0 ? 'text-up' : 'text-down'}>{pct(stats.changeFromFirstPct)}</strong>
        </span>
        <span>
          Last Close: <strong className="text-foreground">{usd(stats.lastClose)}</strong>
        </span>
      </div>

      {/* 3. Interactive Chart SVG Canvas */}
      <div className="relative min-h-0 flex-1 select-none">
        {points.length === 0 ? (
          <div className="flex h-full items-center justify-center font-mono text-[11px] text-dim">
            Loading time series & price distributions…
          </div>
        ) : (
          <svg
            viewBox={`0 0 ${chartW} ${chartH}`}
            preserveAspectRatio="none"
            className="h-full w-full"
            onMouseMove={(e) => {
              const rect = e.currentTarget.getBoundingClientRect()
              const relX = ((e.clientX - rect.left) / rect.width) * chartW
              const clampedX = Math.max(padL, Math.min(padL + plotW, relX))
              const idx = Math.round(((clampedX - padL) / plotW) * (n - 1))
              setHoveredIndex(idx)
            }}
            onMouseLeave={() => setHoveredIndex(null)}
          >
            <defs>
              <linearGradient id="fan2sGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--forecast)" stopOpacity="0.18" />
                <stop offset="100%" stopColor="var(--forecast)" stopOpacity="0.04" />
              </linearGradient>
              <linearGradient id="fan1sGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--forecast)" stopOpacity="0.32" />
                <stop offset="100%" stopColor="var(--forecast)" stopOpacity="0.10" />
              </linearGradient>
            </defs>

            {/* Price Gridlines */}
            {[0, 0.25, 0.5, 0.75, 1.0].map((t) => {
              const yVal = minP + t * priceRange
              const yPos = toY(yVal)
              return (
                <g key={t}>
                  <line
                    x1={padL}
                    y1={yPos}
                    x2={padL + plotW}
                    y2={yPos}
                    stroke="var(--border)"
                    strokeWidth={0.5}
                    strokeDasharray="2 4"
                  />
                  <text
                    x={padL - 6}
                    y={yPos + 3}
                    textAnchor="end"
                    fontSize={8.5}
                    className="fill-muted-foreground font-mono"
                  >
                    ${yVal >= 100 ? yVal.toFixed(0) : yVal.toFixed(2)}
                  </text>
                </g>
              )
            })}

            {/* Forecast Uncertainty Fans */}
            {showBands && forecastFan2s && (
              <path d={forecastFan2s} fill="url(#fan2sGrad)" stroke="var(--forecast)" strokeWidth={0.5} strokeDasharray="2 2" opacity={0.6} />
            )}
            {showBands && forecastFan1s && (
              <path d={forecastFan1s} fill="url(#fan1sGrad)" stroke="var(--forecast)" strokeWidth={0.7} opacity={0.8} />
            )}

            {/* Technical Overlay Curves */}
            {sma30Path && (
              <path d={sma30Path} fill="none" stroke="var(--sma30)" strokeWidth={1} strokeDasharray="3 3" opacity={0.7} />
            )}
            {sma7Path && (
              <path d={sma7Path} fill="none" stroke="var(--sma7)" strokeWidth={1.2} opacity={0.9} />
            )}
            {actualPath && (
              <path d={actualPath} fill="none" stroke="var(--foreground)" strokeWidth={1.5} />
            )}
            {forecastLine && (
              <path d={forecastLine} fill="none" stroke="var(--forecast)" strokeWidth={1.5} strokeDasharray="3 2" />
            )}

            {/* Anchor "NOW" separator line */}
            {(() => {
              const nowIdx = points.findIndex((p) => p.day === 0)
              if (nowIdx < 0) return null
              const nowX = toX(nowIdx)
              return (
                <g>
                  <line
                    x1={nowX}
                    y1={padT}
                    x2={nowX}
                    y2={padT + plotH}
                    stroke="var(--accent)"
                    strokeWidth={1}
                    strokeDasharray="2 2"
                  />
                  <text
                    x={nowX}
                    y={padT - 6}
                    textAnchor="middle"
                    fontSize={8}
                    className="fill-accent font-mono font-bold uppercase"
                  >
                    ASOF NOW
                  </text>
                </g>
              )
            })()}

            {/* Volume Histogram Bars */}
            {points.map((p, i) => {
              if (p.volume == null || p.day > 0) return null
              const x = toX(i)
              const maxVol = Math.max(...points.map((pt) => pt.volume || 0), 10)
              const barH = (p.volume / maxVol) * 32
              const barY = chartH - padB + 40 - barH
              const isUp = (p.dailyReturnPct ?? 0) >= 0
              return (
                <rect
                  key={i}
                  x={x - 2}
                  y={barY}
                  width={4}
                  height={barH}
                  fill={isUp ? 'var(--up)' : 'var(--down)'}
                  opacity={i === hoveredIndex ? 0.9 : 0.4}
                />
              )
            })}

            {/* Optional VPVR Profile on the right axis */}
            {showVpvr &&
              stats.volumeProfile.map((bin, i) => {
                const y1 = toY(bin.priceHi)
                const y2 = toY(bin.priceLo)
                const h = Math.max(1.5, Math.abs(y2 - y1) - 1)
                const w = (bin.volumePct / 100) * 44
                const x = padL + plotW + 4
                return (
                  <rect
                    key={i}
                    x={x}
                    y={Math.min(y1, y2)}
                    width={w}
                    height={h}
                    fill={bin.isPOC ? 'var(--warn)' : 'var(--accent)'}
                    opacity={bin.isPOC ? 0.8 : 0.35}
                    rx={0.5}
                  />
                )
              })}

            {/* Active Hover Crosshair Line */}
            {activePoint && (
              <g>
                <line
                  x1={toX(activeIdx)}
                  y1={padT}
                  x2={toX(activeIdx)}
                  y2={padT + plotH}
                  stroke="var(--accent)"
                  strokeWidth={0.75}
                  strokeDasharray="2 2"
                />
                <circle
                  cx={toX(activeIdx)}
                  cy={toY(activePoint.actual ?? activePoint.forecast ?? stats.lastClose)}
                  r={3}
                  fill="var(--accent)"
                  stroke="var(--background)"
                  strokeWidth={1}
                />
              </g>
            )}

            {/* Date Labels on X-axis */}
            {points
              .filter((_, i) => i % Math.ceil(n / 7) === 0 || i === n - 1)
              .map((p) => {
                const idx = points.indexOf(p)
                return (
                  <text
                    key={p.date + idx}
                    x={toX(idx)}
                    y={chartH - padB + 55}
                    textAnchor="middle"
                    fontSize={8.5}
                    className="fill-muted-foreground font-mono"
                  >
                    {p.date}
                  </text>
                )
              })}
          </svg>
        )}

        {/* Floating Tooltip Box */}
        {activePoint && (
          <div className="pointer-events-none absolute left-14 top-4 rounded-sm border border-border-strong bg-surface/90 p-2 font-mono text-[9.5px] shadow-xl backdrop-blur-sm">
            <div className="mb-1 flex items-center justify-between gap-4 border-b border-border/60 pb-0.5">
              <span className="font-bold text-accent">{activePoint.date}</span>
              <span className="text-dim">{activePoint.day <= 0 ? `${activePoint.day}D` : `+${activePoint.day}D FWD`}</span>
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
              <span className="text-dim">Price:</span>
              <span className="tnum text-right font-bold text-foreground">
                {usd(activePoint.actual ?? activePoint.forecast)}
              </span>
              {activePoint.sma7 != null && (
                <>
                  <span className="text-dim">SMA-7:</span>
                  <span className="tnum text-right text-muted-foreground">{usd(activePoint.sma7)}</span>
                </>
              )}
              {activePoint.sma30 != null && (
                <>
                  <span className="text-dim">SMA-30:</span>
                  <span className="tnum text-right text-muted-foreground">{usd(activePoint.sma30)}</span>
                </>
              )}
              {activePoint.dailyReturnPct != null && (
                <>
                  <span className="text-dim">Daily Return:</span>
                  <span className={`tnum text-right font-semibold ${activePoint.dailyReturnPct >= 0 ? 'text-up' : 'text-down'}`}>
                    {pct(activePoint.dailyReturnPct)}
                  </span>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 4. Bottom Chart Legend & Projected Target Bar */}
      <div className="flex flex-wrap items-center justify-between border-t border-border-strong bg-surface px-3 py-1 font-mono text-[9.5px]">
        <div className="flex items-center gap-4 text-dim">
          <span className="flex items-center gap-1.5">
            <span className="h-0.5 w-3 bg-foreground" />
            <span>Actual</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-0.5 w-3 bg-sma7" />
            <span>SMA-7</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-0.5 w-3 bg-sma30" />
            <span>SMA-30</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-0.5 w-3 bg-forecast" />
            <span>XGB 7D Fan</span>
          </span>
          {showVpvr && (
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-xs bg-warn" />
              <span>POC Level</span>
            </span>
          )}
        </div>

        {forecast && (
          <div className="flex items-center gap-2">
            <span className="text-dim">7D Projected Exit:</span>
            <span className="tnum font-bold text-foreground">{usd(forecast.predicted_7d_price)}</span>
            <span className={`tnum font-semibold ${forecast.predicted_gain_pct >= 0 ? 'text-up' : 'text-down'}`}>
              ({pct(forecast.predicted_gain_pct)})
            </span>
          </div>
        )}
      </div>
    </section>
  )
}