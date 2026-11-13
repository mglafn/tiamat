"use client"

import { useState, useMemo, useRef } from "react"
import { useHistory, useForecast, useSummary } from "@/lib/hooks"
import { buildTimeSeries, type DriftPoint } from "@/lib/series"
import { usd, pct, shortUuid } from "@/lib/format"
import { SetSelector } from "./set-selector"
import { ShieldAlert, TrendingUp } from "lucide-react"

interface ForecastPanelProps {
  uuid: string | null
  selectedFinish?: string
  onFinishChange?: (finish: string) => void
  onSelectUuid?: (uuid: string) => void
}

const FINISHES = ["normal", "foil", "etched"] as const

export function ForecastPanel({
  uuid,
  selectedFinish = "normal",
  onFinishChange,
  onSelectUuid,
}: ForecastPanelProps) {
  const [showBands, setShowBands] = useState(true)

  const containerRef = useRef<HTMLDivElement>(null)

  const { data: history = [] } = useHistory(uuid, selectedFinish, 60)
  const { data: forecast = null } = useForecast(uuid, selectedFinish)
  const { data: summary = null } = useSummary(uuid)

  // 1. Build Time Series & Stats (Explicitly returning object to avoid void type mismatch)
  const { points, stats } = useMemo(() => {
    return buildTimeSeries(history ?? [], forecast ?? null)
  }, [history, forecast])

  // Asset Metadata
  const cardName = summary?.name ?? (uuid ? shortUuid(uuid) : "No Asset Selected")
  const setCode = summary?.set_code ?? "—"
  const collectorNumber = summary?.collector_number ?? null

  // 2. Compute Coordinate Scales for SVG Canvas
  const W = 800
  const H = 380
  const padL = 60
  const padR = 30
  const padT = 35
  const padB = 45
  const plotW = W - padL - padR
  const plotH = H - padT - padB

  // Min / Max domain calculations across historical actuals and forecast uncertainty cones
  const { minP, maxP, minDay, maxDay } = useMemo(() => {
    if (points.length === 0) return { minP: 0, maxP: 100, minDay: -30, maxDay: 7 }

    const allPrices: number[] = []
    const allDays: number[] = []

    points.forEach((p: DriftPoint) => {
      allDays.push(p.day)
      if (p.actual != null && p.actual > 0) allPrices.push(p.actual)
      if (p.sma7 != null && p.sma7 > 0) allPrices.push(p.sma7)
      if (p.upper != null && p.upper > 0) allPrices.push(p.upper)
      if (p.lower != null && p.lower > 0) allPrices.push(p.lower)
      if (p.forecast != null && p.forecast > 0) allPrices.push(p.forecast)
    })

    const rawMin = allPrices.length > 0 ? Math.min(...allPrices) : 1
    const rawMax = allPrices.length > 0 ? Math.max(...allPrices) : 100
    const margin = (rawMax - rawMin) * 0.12 || 1.0

    return {
      minP: Math.max(0.01, rawMin - margin),
      maxP: rawMax + margin,
      minDay: Math.min(...allDays),
      maxDay: Math.max(...allDays),
    }
  }, [points])

  const pRange = maxP - minP || 1
  const dRange = maxDay - minDay || 1

  // Scaler functions
  const getX = (day: number) => padL + ((day - minDay) / dRange) * plotW
  const getY = (price: number) => padT + (1 - (price - minP) / pRange) * plotH

  // 3. SVG Path Construction for Chart Layers
  const historyLinePath = useMemo(() => {
    const valid = points.filter((p: DriftPoint) => p.day <= 0 && p.actual != null)
    if (valid.length === 0) return ""
    return valid
      .map((p: DriftPoint, i: number) => {
        return `${i === 0 ? "M" : "L"} ${getX(p.day).toFixed(1)} ${getY(p.actual!).toFixed(1)}`
      })
      .join(" ")
  }, [points, minDay, dRange, minP, pRange])

  const sma7LinePath = useMemo(() => {
    const valid = points.filter((p: DriftPoint) => p.day <= 0 && p.sma7 != null)
    if (valid.length === 0) return ""
    return valid
      .map((p: DriftPoint, i: number) => {
        return `${i === 0 ? "M" : "L"} ${getX(p.day).toFixed(1)} ${getY(p.sma7!).toFixed(1)}`
      })
      .join(" ")
  }, [points, minDay, dRange, minP, pRange])

  const forecastLinePath = useMemo(() => {
    const valid = points.filter((p: DriftPoint) => p.day >= 0 && p.forecast != null)
    if (valid.length === 0) return ""
    return valid
      .map((p: DriftPoint, i: number) => {
        return `${i === 0 ? "M" : "L"} ${getX(p.day).toFixed(1)} ${getY(p.forecast!).toFixed(1)}`
      })
      .join(" ")
  }, [points, minDay, dRange, minP, pRange])

  const cone2sPolygon = useMemo(() => {
    const valid = points.filter((p: DriftPoint) => p.day >= 0 && p.upper != null && p.lower != null)
    if (valid.length <= 1) return ""
    const top = valid.map((p: DriftPoint) => `${getX(p.day).toFixed(1)},${getY(p.upper!).toFixed(1)}`)
    const bot = valid
      .slice()
      .reverse()
      .map((p: DriftPoint) => `${getX(p.day).toFixed(1)},${getY(p.lower!).toFixed(1)}`)
    return [...top, ...bot].join(" ")
  }, [points, minDay, dRange, minP, pRange])

  const cone1sPolygon = useMemo(() => {
    const valid = points.filter(
      (p: DriftPoint) => p.day >= 0 && p.upper1s != null && p.lower1s != null
    )
    if (valid.length <= 1) return ""
    const top = valid.map((p: DriftPoint) => `${getX(p.day).toFixed(1)},${getY(p.upper1s!).toFixed(1)}`)
    const bot = valid
      .slice()
      .reverse()
      .map((p: DriftPoint) => `${getX(p.day).toFixed(1)},${getY(p.lower1s!).toFixed(1)}`)
    return [...top, ...bot].join(" ")
  }, [points, minDay, dRange, minP, pRange])

  // Y-axis horizontal gridlines
  const yTicks = useMemo(() => {
    const count = 5
    const step = pRange / (count - 1)
    return Array.from({ length: count }, (_: unknown, i: number) => minP + i * step)
  }, [minP, pRange])

  // X-axis vertical day labels
  const xTicks = useMemo(() => {
    return points.filter((p: DriftPoint) => p.day % 10 === 0 || p.day === 0 || p.day === maxDay)
  }, [points, maxDay])

  const nowX = getX(0)

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface font-mono" ref={containerRef}>
      {/* 1. Header Toolbar */}
      <div className="flex flex-wrap items-center justify-between border-b border-border-strong bg-surface-2 px-3 py-1.5 text-[10px]">
        {/* Left: Identifier & Set Selector */}
        <div className="flex items-center gap-2">
          <TrendingUp className="h-3.5 w-3.5 text-accent" />
          <span className="font-bold uppercase tracking-wider text-foreground">
            Asset Forecast
          </span>
          <span className="text-border-strong">|</span>
          <span className="font-semibold text-accent">{cardName}</span>
          <SetSelector
            uuid={uuid}
            currentSetCode={setCode}
            currentCollectorNumber={collectorNumber}
            onSelectUuid={(newUuid) => onSelectUuid?.(newUuid)}
          />
          {uuid && <span className="text-[9px] text-dim">UUID {shortUuid(uuid)}</span>}
        </div>

        {/* Right: Telemetry Metrics & View Toggles */}
        <div className="flex items-center gap-3">
          <div className="hidden items-center gap-2 sm:flex text-dim">
            <span>
              Realized Vol:{" "}
              <strong className="text-foreground font-semibold">
                {stats.realizedVol.toFixed(1)}%
              </strong>
            </span>
            <span>·</span>
            <span>
              Drift:{" "}
              <strong
                className={`font-semibold ${
                  stats.driftVol >= 0 ? "text-up" : "text-down"
                }`}
              >
                {stats.driftVol >= 0 ? "+" : ""}
                {stats.driftVol.toFixed(2)}
              </strong>
            </span>
            <span>·</span>
            <span>
              Last Close:{" "}
              <strong className="text-foreground font-semibold">
                {usd(stats.lastClose)}
              </strong>
            </span>
          </div>

          {/* Display Mode Toggles */}
          <div className="flex items-center gap-1 rounded-sm border border-border bg-surface px-1 py-0.5">
            <button
              type="button"
              onClick={() => setShowBands((b) => !b)}
              className={`rounded-[2px] px-1.5 py-[1px] text-[9px] font-semibold transition-colors ${
                showBands
                  ? "bg-surface-3 text-foreground"
                  : "text-dim hover:text-foreground opacity-50"
              }`}
            >
              ±MAE cone
            </button>
          </div>

          {/* Finish Selector */}
          <div className="flex rounded-sm border border-border">
            {FINISHES.map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => onFinishChange?.(f)}
                className={`px-1.5 py-0.5 text-[9px] font-bold uppercase transition-colors ${
                  selectedFinish === f
                    ? "bg-accent font-bold text-accent-foreground"
                    : "text-dim hover:text-foreground"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 2. Interactive SVG Forecast Chart Canvas */}
      <div className="relative min-h-0 flex-1 overflow-hidden bg-panel/60">
        {points.length === 0 ? (
          <div className="flex h-full items-center justify-center text-[11px] text-dim">
            Select an asset from the Market Spread Book to inspect quantitative forecasts.
          </div>
        ) : (
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="h-full w-full select-none"
            preserveAspectRatio="none"
          >
            <defs>
              {/* Uncertainty Cones Gradient */}
              <linearGradient id="coneGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.35" />
                <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.05" />
              </linearGradient>
            </defs>

            {/* Horizontal Gridlines & Y-Axis Scale */}
            {yTicks.map((price: number, i: number) => {
              const y = getY(price)
              return (
                <g key={`ytick-${i}`}>
                  <line
                    x1={padL}
                    y1={y}
                    x2={W - padR}
                    y2={y}
                    stroke="var(--border)"
                    strokeDasharray="2 3"
                    strokeWidth={0.7}
                  />
                  <text
                    x={padL - 8}
                    y={y + 3.5}
                    textAnchor="end"
                    className="fill-dim text-[9.5px] font-mono tnum"
                  >
                    {usd(price, { compact: true })}
                  </text>
                </g>
              )
            })}

            {/* Vertical X-Axis Date Division Lines */}
            {xTicks.map((p: DriftPoint, i: number) => {
              const x = getX(p.day)
              return (
                <g key={`xtick-${i}`}>
                  <line
                    x1={x}
                    y1={padT}
                    x2={x}
                    y2={H - padB}
                    stroke="var(--border)"
                    strokeDasharray="2 4"
                    strokeWidth={0.5}
                  />
                  <text
                    x={x}
                    y={H - padB + 14}
                    textAnchor="middle"
                    className="fill-dim text-[9px] font-mono uppercase"
                  >
                    {p.date}
                  </text>
                </g>
              )
            })}

            {/* ASOF NOW Vertical Epoch Guard Line */}
            <g>
              <line
                x1={nowX}
                y1={padT - 10}
                x2={nowX}
                y2={H - padB}
                stroke="var(--accent)"
                strokeDasharray="3 3"
                strokeWidth={1.2}
              />
              <text
                x={nowX}
                y={padT - 14}
                textAnchor="middle"
                className="fill-accent text-[9px] font-bold uppercase tracking-wider"
              >
                TODAY
              </text>
            </g>

            {/* 2σ & 1σ Forward Prediction Uncertainty Cones */}

            {showBands && cone2sPolygon && (
              <polygon points={cone2sPolygon} fill="url(#coneGradient)" />
            )}

            {showBands && cone1sPolygon && (
              <polygon
                points={cone1sPolygon}
                fill="var(--accent)"
                opacity={0.12}
              />
            )}

            {/* SMA-7 Line */}
            {sma7LinePath && (
              <path
                d={sma7LinePath}
                fill="none"
                stroke="var(--sma7)"
                strokeWidth={1.2}
                opacity={0.7}
              />
            )}

            {/* Historical Price Action Line */}
            {historyLinePath && (
              <path
                d={historyLinePath}
                fill="none"
                stroke="var(--foreground)"
                strokeWidth={1.8}
              />
            )}

            {/* Forward Forecast Trajectory Line */}
            {forecastLinePath && (
              <path
                d={forecastLinePath}
                fill="none"
                stroke="var(--forecast)"
                strokeWidth={1.8}
                strokeDasharray="4 3"
              />
            )}
          </svg>
        )}
      </div>

      {/* 3. Bottom Telemetry & Risk Sub-Bar */}
      <div className="flex h-8 items-center justify-between border-t border-border-strong bg-surface-2 px-3 text-[10px]">
        {/* Forecast Trajectory Summary */}
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5 text-dim">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" />
            7D Projected Exit:{" "}
            <strong className="text-foreground font-semibold">
              {forecast?.predicted_7d_price ? usd(forecast.predicted_7d_price) : "—"}
            </strong>
            <span
              className={`font-semibold ${
                (forecast?.predicted_gain_pct || 0) >= 0 ? "text-up" : "text-down"
              }`}
            >
              ({pct(forecast?.predicted_gain_pct || 0)})
            </span>
          </span>

          <span className="text-border-strong">|</span>

          <span className="text-dim">
            Model MAE:{" "}
            <strong className="text-muted-foreground font-semibold">
              {forecast?.model_mae ? usd(forecast.model_mae) : "—"}
            </strong>
          </span>

          <span className="text-dim">
            Safety Floor:{" "}
            <strong
              className={`font-semibold ${
                (forecast?.cqr_lpb || 0) >= -15.0 ? "text-up" : "text-warn"
              }`}
            >
              {forecast?.cqr_lpb != null ? pct(forecast.cqr_lpb) : "—"}
            </strong>
          </span>
        </div>

        {/* Defensive Veto Flag Pill */}
        <div>
          {!forecast ? (
            <span className="inline-flex items-center gap-1 rounded-[2px] border border-border bg-surface px-2 py-0.5 text-[9px] font-semibold text-dim">
              <span>NO FORECAST</span>
            </span>
          ) : forecast.is_defensive_vetoed ? (
            <span className="inline-flex items-center gap-1 rounded-[2px] border border-warn/40 bg-warn/10 px-2 py-0.5 text-[9px] font-semibold text-warn">
              <ShieldAlert className="h-3 w-3" />
              <span>TRADE BLOCKED</span>
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-[2px] border border-up/40 bg-up/10 px-2 py-0.5 text-[9px] font-semibold text-up">
              <span>ALPHA SIGNAL ACTIVE</span>
            </span>
          )}
        </div>
      </div>
    </div>
  )
}