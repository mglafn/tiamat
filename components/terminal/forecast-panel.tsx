'use client'

import { useMemo, useRef, useState } from 'react'
import { Activity, BarChart2, Crosshair, Layers, TrendingDown, TrendingUp } from 'lucide-react'
import { useForecast, useHistory, useSummary } from '@/lib/hooks'
import { buildTimeSeries, type DriftPoint } from '@/lib/series'
import { usd, pct, count, shortUuid } from '@/lib/format'

const W = 960
const H = 390
const padL = 60
const padR = 48
const padT = 16
const VOL_H = 54
const VOL_GAP = 10
const padB = 26

const FINISHES = ['normal', 'foil', 'etched'] as const
const VENDORS = ['tcgplayer', 'cardkingdom', 'starcitygames'] as const
type PriceMode = 'nominal' | 'risk'

interface ForecastPanelProps {
  uuid: string | null
  selectedFinish: string
  onFinishChange: (finish: string) => void
}

export function ForecastPanel({ uuid, selectedFinish, onFinishChange }: ForecastPanelProps) {
  const [vendor, setVendor] = useState<string>('tcgplayer')
  const [priceMode, setPriceMode] = useState<PriceMode>('nominal')
  const [showBands, setShowBands] = useState(true)
  const [showVPVR, setShowVPVR] = useState(true)
  const [hoverDay, setHoverDay] = useState<number | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  const finish = selectedFinish
  const setFinish = onFinishChange

  const { data: forecast } = useForecast(uuid, vendor, finish)
  const { data: history = [] } = useHistory(uuid, vendor, finish, 45)
  const { data: summary } = useSummary(uuid)

  const { points, stats } = useMemo(() => {
    if (!uuid || history.length === 0) {
      return {
        points: [] as DriftPoint[],
        stats: {
          realizedVol: 0,
          lastClose: 0,
          driftVol: 0,
          changeFromFirstPct: 0,
          volumeProfile: [],
        },
      }
    }
    return buildTimeSeries(history, forecast ?? null)
  }, [uuid, history, forecast])

  const isIlliquid = Boolean(uuid) && history.length === 0

  const geom = useMemo(() => {
    if (points.length === 0) return null

    const priceKey: keyof DriftPoint = priceMode === 'risk' ? 'riskAdj' : 'actual'

    const vals: number[] = []
    for (const p of points) {
      const series: (number | null)[] = [
        p[priceKey] as number | null,
        p.sma7,
        p.sma30,
        p.forecast,
        p.upper,
        p.lower,
      ]
      if (showBands) series.push(p.bollUpper, p.bollLower)
      for (const v of series) {
        if (v != null && !isNaN(v) && v > 0) vals.push(v)
      }
    }
    if (vals.length === 0) return null

    const min = Math.min(...vals)
    const max = Math.max(...vals)
    const pad = (max - min) * 0.12 || max * 0.08
    const lo = Math.max(0.01, min - pad)
    const hi = max + pad

    const priceBottom = H - padB - VOL_H - VOL_GAP
    const plotW = W - padL - padR
    const plotH = priceBottom - padT

    const minDay = points[0]?.day ?? 0
    const maxDay = points[points.length - 1]?.day ?? 7
    const daySpan = Math.max(1, maxDay - minDay)

    const x = (day: number) => padL + ((day - minDay) / daySpan) * plotW
    const y = (val: number) => padT + (1 - (val - lo) / Math.max(0.001, hi - lo)) * plotH
    const nowX = x(0)

    const line = (key: keyof DriftPoint) =>
      points
        .map((p: DriftPoint) =>
          p[key] == null || isNaN(p[key] as number)
            ? null
            : `${x(p.day).toFixed(1)},${y(p[key] as number).toFixed(1)}`
        )
        .filter(Boolean)
        .join(' ')

    const makePolygon = (upKey: keyof DriftPoint, lowKey: keyof DriftPoint) => {
      const upper = points.filter((p) => p[upKey] != null && !isNaN(p[upKey] as number))
      const lower = points.filter((p) => p[lowKey] != null && !isNaN(p[lowKey] as number))
      if (!upper.length || !lower.length) return ''
      const up = upper.map((p) => `${x(p.day).toFixed(1)},${y(p[upKey] as number).toFixed(1)}`)
      const lowRev = [...lower]
        .reverse()
        .map((p) => `${x(p.day).toFixed(1)},${y(p[lowKey] as number).toFixed(1)}`)
      return `${up.join(' ')} ${lowRev.join(' ')}`
    }

    const cone2s = makePolygon('upper', 'lower')
    const cone1s = makePolygon('upper1s', 'lower1s')
    const band = showBands ? makePolygon('bollUpper', 'bollLower') : ''

    const volVals = points.filter((p) => p.day <= 0).map((p: DriftPoint) => p.volume ?? 0)
    const volMax = Math.max(1, ...volVals)
    const volTop = priceBottom + VOL_GAP
    const barW = Math.max(2, (plotW / (points.length + 2)) * 0.72)
    const volBar = (v: number) => (v / volMax) * (VOL_H - 4)

    const ticks = 5
    const yTicks = Array.from({ length: ticks }, (_, i: number) => {
      const val = lo + ((hi - lo) * i) / (ticks - 1)
      return { val, y: y(val) }
    })

    const xLabels = points
      .filter((_: DriftPoint, i: number) => i % 8 === 0 || points[i].day === 0)
      .map((p: DriftPoint) => ({
        x: x(p.day),
        label: p.day === 0 ? 'NOW' : p.date,
        now: p.day === 0,
      }))

    return {
      x,
      y,
      nowX,
      line,
      cone2s,
      cone1s,
      band,
      yTicks,
      xLabels,
      minDay,
      maxDay,
      priceBottom,
      plotW,
      plotH,
      volTop,
      barW,
      volBar,
      priceKey,
      lo,
      hi,
    }
  }, [points, priceMode, showBands])

  const hovered = useMemo(() => {
    if (hoverDay == null || points.length === 0) return null
    return points.reduce<DriftPoint | null>((best: DriftPoint | null, p: DriftPoint) => {
      if (best == null) return p
      return Math.abs(p.day - hoverDay) < Math.abs(best.day - hoverDay) ? p : best
    }, null)
  }, [hoverDay, points])

  function handleMove(e: React.MouseEvent<SVGSVGElement>) {
    if (!geom || !svgRef.current) return
    const rect = svgRef.current.getBoundingClientRect()
    const relX = ((e.clientX - rect.left) / rect.width) * W
    const frac = (relX - padL) / geom.plotW
    const day = geom.minDay + frac * (geom.maxDay - geom.minDay)
    setHoverDay(Math.round(day))
  }

  const name = summary?.name ?? (uuid ? shortUuid(uuid) : null)
  const gainPositive = (forecast?.predicted_gain_pct ?? 0) >= 0

  return (
    <section className="flex h-full min-h-0 flex-col bg-panel" aria-label="Asset forecast and historical series">
      {/* Control Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-strong bg-surface px-3 py-1.5">
        <div className="flex items-baseline gap-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-foreground">Asset Forecast</h2>
          {name && (
            <span className="text-[11px] text-accent">
              {name}
              {uuid && <span className="ml-2 text-dim font-mono text-[10px]">UUID {shortUuid(uuid)}</span>}
              {isIlliquid && (
                <span className="ml-2 rounded-sm border border-warn/40 bg-warn/10 px-1.5 py-0.5 text-[9px] font-mono text-warn">
                  UNQUOTED
                </span>
              )}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-[10px] uppercase">
          {forecast?.directional_accuracy_pct != null && (
            <span className="hidden text-dim xl:inline">
              Model Acc: <span className="tnum font-semibold text-foreground">{forecast.directional_accuracy_pct}%</span>
            </span>
          )}

          <div className="flex overflow-hidden rounded-sm border border-border">
            <button
              type="button"
              onClick={() => setPriceMode('nominal')}
              className={`px-1.5 py-0.5 transition-colors ${
                priceMode === 'nominal'
                  ? 'bg-surface-2 font-semibold text-foreground'
                  : 'text-dim hover:text-muted-foreground'
              }`}
            >
              nominal
            </button>
            <button
              type="button"
              onClick={() => setPriceMode('risk')}
              className={`px-1.5 py-0.5 transition-colors ${
                priceMode === 'risk'
                  ? 'bg-accent font-semibold text-accent-foreground'
                  : 'text-dim hover:text-muted-foreground'
              }`}
            >
              risk-adj
            </button>
          </div>

          <button
            type="button"
            onClick={() => setShowBands((b) => !b)}
            className={`rounded-sm border px-1.5 py-0.5 transition-colors ${
              showBands
                ? 'border-band/50 bg-band/10 text-band font-medium'
                : 'border-border text-dim hover:text-muted-foreground'
            }`}
          >
            2σ bands
          </button>

          <button
            type="button"
            onClick={() => setShowVPVR((v) => !v)}
            className={`flex items-center gap-1 rounded-sm border px-1.5 py-0.5 transition-colors ${
              showVPVR
                ? 'border-accent/40 bg-accent/10 text-accent font-medium'
                : 'border-border text-dim hover:text-muted-foreground'
            }`}
          >
            <BarChart2 className="h-2.5 w-2.5" />
            <span>VPVR</span>
          </button>

          <div className="hidden overflow-hidden rounded-sm border border-border lg:flex">
            {VENDORS.map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setVendor(v)}
                className={`px-1.5 py-0.5 transition-colors ${
                  vendor === v ? 'bg-surface-2 font-semibold text-foreground' : 'text-dim hover:text-muted-foreground'
                }`}
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
                className={`px-1.5 py-0.5 transition-colors ${
                  finish === f
                    ? 'bg-accent font-semibold text-accent-foreground'
                    : 'text-dim hover:text-muted-foreground'
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Quantitative Sub-Header */}
      {geom && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b border-border bg-surface/40 px-3 py-1 text-[10px] uppercase">
          <StatChip
            label="Realized Vol (ann.)"
            value={`${stats.realizedVol.toFixed(1)}%`}
            tone={stats.realizedVol > 40 ? 'text-warn' : 'text-foreground'}
          />
          <StatChip
            label="Drift / Vol"
            value={stats.driftVol.toFixed(2)}
            tone={stats.driftVol >= 0 ? 'text-up' : 'text-down'}
          />
          <StatChip
            label="Historical Range"
            value={`${pct(stats.changeFromFirstPct)}`}
            tone={stats.changeFromFirstPct >= 0 ? 'text-up' : 'text-down'}
          />
          <StatChip label="Last Close" value={usd(stats.lastClose, { compact: true })} tone="text-foreground" />
          <span className="ml-auto flex items-center gap-1 text-dim">
            <Activity className="h-3 w-3 text-accent" />
            {priceMode === 'risk' ? 'VOLATILITY-PENALIZED TRAJECTORY' : 'RAW MARGINAL CLOSE'}
          </span>
        </div>
      )}

      {/* Primary SVG Charting Canvas */}
      <div className="relative flex min-h-0 flex-1 items-center justify-center p-2">
        {!uuid && (
          <div className="flex flex-col items-center justify-center gap-2 text-center text-dim">
            <Crosshair className="h-8 w-8 text-dim/60" />
            <span className="text-[11px]">Select an asset from the order book or press ⌘K to search</span>
          </div>
        )}

        {isIlliquid && (
          <div className="flex h-full w-full flex-col items-center justify-center gap-1.5 p-6 text-center">
            <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-warn">
              Illiquid Instrument · Zero Order Book Depth
            </span>
            <span className="max-w-md text-[10px] leading-relaxed text-dim">
              No verified secondary market transactions recorded for this finish/vendor variant. Inference targets and technical indicators suspended.
            </span>
          </div>
        )}

        {uuid && !isIlliquid && geom && (
          <svg
            ref={svgRef}
            viewBox={`0 0 ${W} ${H}`}
            className="h-full w-full max-h-full cursor-crosshair select-none"
            preserveAspectRatio="xMidYMid meet"
            role="img"
            aria-label="Price history, Bollinger bands, forecast, and volume"
            onMouseMove={handleMove}
            onMouseLeave={() => setHoverDay(null)}
          >
            <defs>
              {/* Gaussian-like Probability Density Fan Gradients */}
              <linearGradient id="cone-density-2s" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--forecast)" stopOpacity="0.04" />
                <stop offset="50%" stopColor="var(--forecast)" stopOpacity="0.22" />
                <stop offset="100%" stopColor="var(--forecast)" stopOpacity="0.04" />
              </linearGradient>
              <linearGradient id="cone-density-1s" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--forecast)" stopOpacity="0.10" />
                <stop offset="50%" stopColor="var(--forecast)" stopOpacity="0.32" />
                <stop offset="100%" stopColor="var(--forecast)" stopOpacity="0.10" />
              </linearGradient>
              {/* Volume Profile Gradient */}
              <linearGradient id="vpvr-gradient" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.05" />
                <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.25" />
              </linearGradient>
              <linearGradient id="vpvr-poc" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="var(--warn)" stopOpacity="0.15" />
                <stop offset="100%" stopColor="var(--warn)" stopOpacity="0.45" />
              </linearGradient>
            </defs>

            {/* Horizontal Gridlines */}
            {geom.yTicks.map((t: { val: number; y: number }, i: number) => (
              <g key={i}>
                <line x1={padL} y1={t.y} x2={W - padR} y2={t.y} stroke="var(--border)" strokeWidth={0.5} strokeDasharray="2 4" />
                <text x={padL - 6} y={t.y + 3} textAnchor="end" className="fill-dim font-mono" fontSize={8.5}>
                  {t.val >= 1000 ? `$${(t.val / 1000).toFixed(1)}K` : `$${t.val.toFixed(t.val >= 100 ? 0 : 2)}`}
                </text>
              </g>
            ))}

            {/* Volume Profile by Price (VPVR) on Right Axis */}
            {showVPVR &&
              stats.volumeProfile.map((b, i) => {
                const yTop = geom.y(b.priceHi)
                const yBot = geom.y(b.priceLo)
                const barHeight = Math.max(1, yBot - yTop)
                const vpvrWidth = (b.volumePct / 100) * (padR + 60)
                const xPos = W - padR - vpvrWidth

                return (
                  <g key={`vpvr-${i}`}>
                    <rect
                      x={xPos}
                      y={yTop}
                      width={vpvrWidth}
                      height={barHeight - 0.5}
                      fill={b.isPOC ? 'url(#vpvr-poc)' : 'url(#vpvr-gradient)'}
                    />
                    {b.isPOC && (
                      <line
                        x1={padL}
                        y1={geom.y(b.priceMid)}
                        x2={W - padR}
                        y2={geom.y(b.priceMid)}
                        stroke="var(--warn)"
                        strokeWidth={0.75}
                        strokeDasharray="1 3"
                        opacity={0.7}
                      />
                    )}
                  </g>
                )
              })}

            {/* Forward Horizon Background Tint */}
            <rect
              x={geom.nowX}
              y={padT}
              width={Math.max(0, W - padR - geom.nowX)}
              height={geom.priceBottom - padT}
              fill="var(--accent)"
              opacity={0.03}
            />

            {/* Uncertainty Probability Cones */}
            {geom.cone2s && <polygon points={geom.cone2s} fill="url(#cone-density-2s)" />}
            {geom.cone1s && <polygon points={geom.cone1s} fill="url(#cone-density-1s)" />}

            {/* Bollinger Ribbon & Envelopes */}
            {showBands && geom.band && <polygon points={geom.band} fill="var(--band)" opacity={0.07} />}
            {showBands && (
              <>
                <polyline points={geom.line('bollUpper')} fill="none" stroke="var(--band)" strokeWidth={0.75} strokeDasharray="1 3" opacity={0.65} />
                <polyline points={geom.line('bollLower')} fill="none" stroke="var(--band)" strokeWidth={0.75} strokeDasharray="1 3" opacity={0.65} />
              </>
            )}

            {/* Moving Averages */}
            <polyline points={geom.line('sma30')} fill="none" stroke="var(--sma30)" strokeWidth={1} strokeDasharray="2 2" />
            <polyline points={geom.line('sma7')} fill="none" stroke="var(--sma7)" strokeWidth={1.25} />

            {/* Primary Price Series */}
            <polyline
              points={geom.line(geom.priceKey)}
              fill="none"
              stroke={priceMode === 'risk' ? 'var(--accent)' : 'var(--hist)'}
              strokeWidth={1.75}
            />

            {/* 7-Day Forecast Trajectory */}
            <polyline
              points={geom.line('forecast')}
              fill="none"
              stroke="var(--forecast)"
              strokeWidth={2}
              strokeDasharray="4 3"
              strokeLinecap="round"
            />

            {/* Present Timestamp Anchor Line */}
            <line
              x1={geom.nowX}
              y1={padT}
              x2={geom.nowX}
              y2={geom.priceBottom}
              stroke="var(--border-strong)"
              strokeWidth={1}
              strokeDasharray="2 2"
            />

            {/* Sub-Chart: Traded Volume Bars */}
            <line x1={padL} y1={geom.volTop} x2={W - padR} y2={geom.volTop} stroke="var(--border)" strokeWidth={0.5} />
            <text x={padL - 6} y={geom.volTop + 10} textAnchor="end" className="fill-dim font-mono font-bold" fontSize={8}>
              VOL
            </text>
            {points.map((p: DriftPoint, i: number) => {
              if (p.volume == null || p.day > 0) return null
              const barH = geom.volBar(p.volume)
              const isUp = (p.dailyReturnPct ?? 0) >= 0

              return (
                <rect
                  key={i}
                  x={geom.x(p.day) - geom.barW / 2}
                  y={geom.volTop + VOL_H - barH}
                  width={geom.barW}
                  height={Math.max(2, barH)}
                  fill={hovered?.day === p.day ? 'var(--accent)' : isUp ? 'var(--up)' : 'var(--down)'}
                  opacity={hovered?.day === p.day ? 1 : isUp ? 0.65 : 0.45}
                  rx={0.5}
                />
              )
            })}

            {/* 7D Target Horizon Coordinate */}
            {forecast && points.length > 0 && (
              <circle
                cx={geom.x(points[points.length - 1].day)}
                cy={geom.y(forecast.predicted_7d_price)}
                r={3.5}
                fill="var(--forecast)"
                stroke="var(--background)"
                strokeWidth={1.5}
              />
            )}

            {/* Interactive Crosshair Alignment */}
            {hovered && (
              <g pointerEvents="none">
                <line
                  x1={geom.x(hovered.day)}
                  y1={padT}
                  x2={geom.x(hovered.day)}
                  y2={geom.volTop + VOL_H}
                  stroke="var(--accent)"
                  strokeWidth={0.75}
                  strokeDasharray="2 2"
                  opacity={0.8}
                />
                {hovered[geom.priceKey] != null && (
                  <circle
                    cx={geom.x(hovered.day)}
                    cy={geom.y(hovered[geom.priceKey] as number)}
                    r={3.5}
                    fill="var(--accent)"
                    stroke="var(--background)"
                    strokeWidth={1.5}
                  />
                )}
              </g>
            )}

            {/* X-Axis Date Labels */}
            {geom.xLabels.map((l: { x: number; label: string; now: boolean }, i: number) => (
              <text
                key={i}
                x={l.x}
                y={H - 8}
                textAnchor="middle"
                fontSize={8.5}
                className={`font-mono ${l.now ? 'fill-accent font-semibold' : 'fill-dim'}`}
              >
                {l.label}
              </text>
            ))}
          </svg>
        )}

        {/* HUD Crosshair Tooltip */}
        {hovered && geom && (
          <div className="pointer-events-none absolute left-3 top-10 z-20 min-w-44 rounded-sm border border-border-strong bg-surface/95 p-2.5 text-[10px] shadow-2xl backdrop-blur-md">
            <div className="mb-1.5 flex items-center justify-between border-b border-border/60 pb-1 font-mono">
              <span className="font-semibold uppercase tracking-wider text-accent">
                {hovered.day === 0 ? 'T+0 (NOW)' : hovered.day > 0 ? `T+${hovered.day} (FWD)` : hovered.date}
              </span>
              <span className="text-dim">{hovered.date}</span>
            </div>
            <div className="space-y-1">
              <InspectRow
                label={priceMode === 'risk' ? 'Risk-Adj' : 'Close'}
                value={usd(hovered[geom.priceKey] as number | null, { compact: true })}
                tone="text-foreground font-semibold"
              />
              {hovered.forecast != null && hovered.day >= 0 && (
                <InspectRow label="Forecast (XGB)" value={usd(hovered.forecast, { compact: true })} tone="text-forecast font-semibold" />
              )}
              {hovered.upper != null && hovered.day > 0 && (
                <InspectRow
                  label="2σ Range"
                  value={`${usd(hovered.lower, { compact: true })} – ${usd(hovered.upper, { compact: true })}`}
                  tone="text-dim"
                />
              )}
              <InspectRow label="SMA-7" value={usd(hovered.sma7, { compact: true })} tone="text-sma7" />
              <InspectRow label="SMA-30" value={usd(hovered.sma30, { compact: true })} tone="text-muted-foreground" />
              {showBands && hovered.bollUpper != null && (
                <InspectRow
                  label="Bollinger 2σ"
                  value={`${usd(hovered.bollLower, { compact: true })} – ${usd(hovered.bollUpper, { compact: true })}`}
                  tone="text-band"
                />
              )}
              {hovered.volume != null && (
                <InspectRow
                  label="Daily Vol"
                  value={`${count(hovered.volume)} (${hovered.dailyReturnPct ? pct(hovered.dailyReturnPct) : '—'})`}
                  tone="text-muted-foreground"
                />
              )}
            </div>
          </div>
        )}
      </div>

      {/* Legend & Horizon Metric Footer */}
      {forecast && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border bg-surface/50 px-3 py-1.5 text-[10px] uppercase">
          <Legend color="var(--hist)" label={priceMode === 'risk' ? 'Risk-Adj' : 'Actual'} />
          <Legend color="var(--sma7)" label="SMA-7" />
          <Legend color="var(--sma30)" label="SMA-30" dashed />
          {showBands && <Legend color="var(--band)" label="Bollinger 2σ" dashed />}
          <Legend color="var(--forecast)" label="XGB 7D Fan" dashed />
          {showVPVR && <Legend color="var(--warn)" label="POC Level" dashed />}
          <span className="ml-auto flex items-center gap-2">
            <span className="text-dim">7D Projected Exit:</span>
            <span className="tnum font-semibold text-forecast">{usd(forecast.predicted_7d_price, { compact: true })}</span>
            <span className={`tnum flex items-center gap-0.5 font-semibold ${gainPositive ? 'text-up' : 'text-down'}`}>
              {gainPositive ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
              {pct(forecast.predicted_gain_pct)}
            </span>
          </span>
        </div>
      )}
    </section>
  )
}

function StatChip({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="text-dim">{label}</span>
      <span className={`tnum font-semibold ${tone}`}>{value}</span>
    </span>
  )
}

function InspectRow({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-center justify-between gap-4 font-mono text-[9.5px]">
      <span className="uppercase text-dim">{label}</span>
      <span className={`tnum ${tone ?? 'text-foreground'}`}>{value}</span>
    </div>
  )
}

function Legend({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span className="flex items-center gap-1.5 font-mono text-[9.5px]">
      <span
        className="inline-block h-0.5 w-3.5"
        style={{ background: dashed ? 'none' : color, borderTop: dashed ? `1.5px dashed ${color}` : undefined }}
      />
      <span className="text-muted-foreground">{label}</span>
    </span>
  )
}