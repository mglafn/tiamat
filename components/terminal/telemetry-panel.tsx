'use client'

import { useMemo, useState } from 'react'
import { AlertTriangle, Sliders } from 'lucide-react'
import { useForecast, useSummary } from '@/lib/hooks'
import { runEconomics, type EconInputs, type WaterfallStep } from '@/lib/economics'
import { usd, pct, signedUsd, shortUuid } from '@/lib/format'

interface TelemetryPanelProps {
  uuid: string | null
  selectedFinish?: string
  onSelectUuid?: (uuid: string) => void
}

export function TelemetryPanel({ uuid, selectedFinish = 'normal' }: TelemetryPanelProps) {
  const { data: summary } = useSummary(uuid)
  const { data: forecast } = useForecast(uuid, 'tcgplayer', selectedFinish)

  const [pro, setPro] = useState(true)
  const [hurdle, setHurdle] = useState(10)
  const [taxRate, setTaxRate] = useState(7.5)
  const [freight, setFreight] = useState(0.09)
  const [kappa, setKappa] = useState(98.5)
  const [activeTab, setActiveTab] = useState<'waterfall' | 'sensitivity'>('waterfall')

  const name = summary?.name ?? (uuid ? shortUuid(uuid) : null)
  const setCode = summary?.set_code ?? '—'
  const collectorNum = summary?.collector_number ? `#${summary.collector_number}` : ''

  const econ = useMemo(() => {
    if (!forecast || forecast.current_price <= 0) return null
    const inputs: EconInputs = {
      exitPrice: forecast.predicted_7d_price,
      acqPrice: forecast.current_price,
      pro,
      taxRate: taxRate / 100,
      freightPerUnit: freight,
      kappa: kappa / 100,
      hurdlePct: hurdle,
    }
    return runEconomics(inputs)
  }, [forecast, pro, taxRate, freight, kappa, hurdle])

  const isDeadZone =
    forecast?.is_dead_zone_clamped ||
    (econ && econ.exitPrice >= 2.5 && econ.exitPrice <= 2.67)

  // 2D Sensitivity Heatmap Matrix generator
  const sensitivityMatrix = useMemo(() => {
    if (!forecast || forecast.current_price <= 0) return []
    const taxes = [5.0, 7.5, 10.0]
    const kappas = [99.0, 97.0, 95.0]
    return taxes.map((t) => {
      return kappas.map((k) => {
        const res = runEconomics({
          exitPrice: forecast.predicted_7d_price,
          acqPrice: forecast.current_price,
          pro,
          taxRate: t / 100,
          freightPerUnit: freight,
          kappa: k / 100,
          hurdlePct: hurdle,
        })
        return {
          tax: t,
          kappa: k,
          profit: res.netProfit,
          roi: res.netRoiPct,
          clears: res.clearsHurdle,
        }
      })
    })
  }, [forecast, pro, freight, hurdle])

  return (
    <section className="flex min-h-0 flex-col border-l border-border-strong bg-panel" aria-label="Unit economics and execution telemetry">
      {/* Panel Header */}
      <div className="flex items-center justify-between border-b border-border-strong bg-surface px-3 py-1.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-foreground">Unit Economics</h2>
        {econ && (
          <span className={`tnum font-mono text-[10px] font-bold ${econ.clearsHurdle ? 'text-up' : 'text-down'}`}>
            {econ.clearsHurdle ? 'CLEARS HURDLE' : 'BELOW HURDLE'}
          </span>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {!uuid && <p className="p-3 text-[11px] text-dim">No asset selected.</p>}

        {uuid && (
          <>
            {/* SKU Overview */}
            <div className="border-b border-border/60 bg-surface/40 p-3 font-mono">
              <div className="flex items-center justify-between text-[10px] uppercase text-dim">
                <span>Selected Instrument</span>
                {collectorNum && <span className="text-dim">{collectorNum}</span>}
              </div>
              <div className="mt-0.5 text-pretty text-[13px] font-semibold text-accent">{name}</div>
              <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-[10px]">
                <span className="text-dim">
                  Finish <span className="capitalize text-foreground font-semibold">{selectedFinish}</span>
                </span>
                <span className="text-dim">
                  Set <span className="font-semibold text-foreground">{setCode}</span>
                </span>
                {summary?.edhrec_rank != null && (
                  <span className="text-dim">
                    EDHREC <span className="font-semibold text-up">#{summary.edhrec_rank.toLocaleString()}</span>
                  </span>
                )}
              </div>
            </div>

            {!econ ? (
              <div className="m-3 rounded-sm border border-warn/30 bg-warn/5 p-3 font-mono">
                <div className="flex items-center justify-between text-[10px] uppercase">
                  <span className="font-semibold text-warn">Execution Halted</span>
                  <span className="text-[9px] text-dim">CODE: ILLIQUID</span>
                </div>
                <p className="mt-1 text-[10px] leading-relaxed text-dim">
                  Zero active order book depth on tracked marketplaces. Automated Direct/SYP fulfillment and margin routing are offline for this variant.
                </p>
              </div>
            ) : (
              <>
                {/* Mode Selector Tabs */}
                <div className="flex border-b border-border text-[10px] font-mono uppercase">
                  <button
                    type="button"
                    onClick={() => setActiveTab('waterfall')}
                    className={`flex-1 py-1.5 font-semibold transition-colors ${
                      activeTab === 'waterfall'
                        ? 'border-b-2 border-accent bg-surface text-accent'
                        : 'text-dim hover:text-foreground'
                    }`}
                  >
                    Fee Waterfall
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab('sensitivity')}
                    className={`flex-1 py-1.5 font-semibold transition-colors ${
                      activeTab === 'sensitivity'
                        ? 'border-b-2 border-accent bg-surface text-accent'
                        : 'text-dim hover:text-foreground'
                    }`}
                  >
                    Sensitivity Matrix
                  </button>
                </div>

                {/* View 1: Fee Waterfall */}
                {activeTab === 'waterfall' && (
                  <div className="border-b border-border/60 p-3 font-mono">
                    <div className="mb-2 flex items-center justify-between text-[10px] uppercase text-dim">
                      <span>Fee Decomposition</span>
                      <span className="tnum text-warn">{econ.feeLoadPct.toFixed(1)}% load</span>
                    </div>
                    <Waterfall steps={econ.steps} />
                  </div>
                )}

                {/* View 2: Sensitivity Heatmap */}
                {activeTab === 'sensitivity' && (
                  <div className="border-b border-border/60 p-3 font-mono">
                    <div className="mb-2 flex items-center justify-between text-[10px] uppercase text-dim">
                      <span>Net Profit Matrix (Tax vs κ)</span>
                      <span className="text-[9px] text-dim">3x3 Scenario</span>
                    </div>
                    <div className="grid grid-cols-4 gap-1 text-[9.5px]">
                      <div className="text-dim">Tax \ κ</div>
                      <div className="text-center font-bold text-foreground">99.0%</div>
                      <div className="text-center font-bold text-foreground">97.0%</div>
                      <div className="text-center font-bold text-foreground">95.0%</div>
                      {sensitivityMatrix.map((row, rIdx) => (
                        <div key={rIdx} className="contents">
                          <div className="flex items-center text-dim font-bold">{row[0].tax}%</div>
                          {row.map((cell, cIdx) => (
                            <div
                              key={cIdx}
                              className={`flex flex-col items-center justify-center rounded-[2px] p-1 text-center font-bold ${
                                cell.profit >= 0
                                  ? cell.clears
                                    ? 'bg-up/20 text-up border border-up/30'
                                    : 'bg-warn/15 text-warn border border-warn/25'
                                  : 'bg-down/20 text-down border border-down/30'
                              }`}
                            >
                              <span>{signedUsd(cell.profit)}</span>
                              <span className="text-[8px] opacity-75">{pct(cell.roi)}</span>
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Dead-Zone Fee Cliff Warning */}
                {isDeadZone && (
                  <div className="mx-3 mt-3 rounded-sm border border-warn/40 bg-warn/10 p-2.5 font-mono text-[10px] text-warn">
                    <div className="flex items-center gap-1.5 font-bold uppercase">
                      <AlertTriangle className="h-3.5 w-3.5" />
                      <span>[$2.50, $2.67] Dead-Zone Cliff Triggered</span>
                    </div>
                    <p className="mt-1 text-[9.5px] leading-relaxed text-dim">
                      Target exit price intersects the fixed $1.12 step-up commission cliff. Payout clamped to $2.49 to eliminate severe marginal drag.
                    </p>
                    <div className="mt-2 h-9 w-full border-b border-l border-warn/30">
                      <svg viewBox="0 0 100 30" className="h-full w-full overflow-visible">
                        <path
                          d="M 0,22 L 48,8 L 50,26 L 100,6"
                          fill="none"
                          stroke="var(--warn)"
                          strokeWidth="1.5"
                        />
                        <circle cx="48" cy="8" r="2.5" fill="var(--up)" />
                        <circle cx="50" cy="26" r="2.5" fill="var(--down)" />
                        <text x="48" y="5" fontSize="6" fill="var(--up)" textAnchor="middle">
                          $2.49 ($1.25)
                        </text>
                        <text x="65" y="28" fontSize="6" fill="var(--down)" textAnchor="middle">
                          $2.50 ($1.09)
                        </text>
                      </svg>
                    </div>
                  </div>
                )}

                {/* Payout Verdict Block */}
                <div className="border-b border-border/60 p-3 font-mono">
                  <div className="grid grid-cols-2 gap-2">
                    <VerdictCell label="Net Payout" value={usd(econ.netPayout, { compact: true })} tone="text-foreground" />
                    <VerdictCell label="Landed Basis" value={usd(econ.landedBasis, { compact: true })} tone="text-muted-foreground" />
                    <VerdictCell
                      label="Net Profit / Unit"
                      value={signedUsd(econ.netProfit)}
                      tone={econ.netProfit >= 0 ? 'text-up' : 'text-down'}
                    />
                    <VerdictCell
                      label="Net ROI"
                      value={pct(econ.netRoiPct)}
                      tone={econ.clearsHurdle ? 'text-up' : econ.netRoiPct >= 0 ? 'text-warn' : 'text-down'}
                      big
                    />
                  </div>

                  {/* Hurdle Gauge */}
                  <div className="mt-3">
                    <div className="mb-1 flex items-center justify-between text-[9px] uppercase text-dim">
                      <span>ROI vs Hurdle</span>
                      <span className="tnum">
                        {pct(econ.netRoiPct)} / {hurdle.toFixed(0)}%
                      </span>
                    </div>
                    <HurdleGauge roi={econ.netRoiPct} hurdle={hurdle} />
                    <div className="mt-1.5 flex items-center justify-between text-[9px] text-dim">
                      <span>Breakeven exit: <span className="tnum text-muted-foreground">{usd(econ.breakevenExit, { compact: true })}</span></span>
                      <span>Gross margin: <span className="tnum text-muted-foreground">{pct(econ.grossMarginPct, false)}</span></span>
                    </div>
                  </div>
                </div>

                {/* Interactive Scenario Assumptions */}
                <div className="p-3 font-mono">
                  <div className="mb-2.5 flex items-center justify-between text-[10px] uppercase text-dim">
                    <span className="flex items-center gap-1">
                      <Sliders className="h-3 w-3 text-accent" />
                      <span>Execution Parameters</span>
                    </span>
                  </div>

                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-[10px] uppercase text-dim">Seller Tier</span>
                    <div className="flex overflow-hidden rounded-sm border border-border text-[10px]">
                      <button
                        type="button"
                        onClick={() => setPro(true)}
                        className={`px-2 py-0.5 transition-colors ${
                          pro ? 'bg-accent font-semibold text-accent-foreground' : 'text-dim hover:text-muted-foreground'
                        }`}
                      >
                        PRO (8.95%)
                      </button>
                      <button
                        type="button"
                        onClick={() => setPro(false)}
                        className={`px-2 py-0.5 transition-colors ${
                          !pro ? 'bg-accent font-semibold text-accent-foreground' : 'text-dim hover:text-muted-foreground'
                        }`}
                      >
                        NON-PRO (10.75%)
                      </button>
                    </div>
                  </div>

                  <Slider label="ROI Hurdle" value={hurdle} min={0} max={40} step={1} suffix="%" onChange={setHurdle} />
                  <Slider label="Sales Tax" value={taxRate} min={0} max={12} step={0.5} suffix="%" onChange={setTaxRate} />
                  <Slider label="Outbound Freight" value={freight} min={0} max={0.5} step={0.01} prefix="$" onChange={setFreight} />
                  <Slider label="Condition κ" value={kappa} min={80} max={100} step={0.5} suffix="%" onChange={setKappa} />
                </div>
              </>
            )}
          </>
        )}
      </div>
    </section>
  )
}

function Waterfall({ steps }: { steps: WaterfallStep[] }) {
  const balances = steps.map((s) => s.balance)
  const max = Math.max(...balances, steps[0]?.delta ?? 0)
  const min = 0
  const range = Math.max(0.01, max - min)
  const rowH = 24
  const labelW = 118
  const barArea = 168
  const chartW = labelW + barArea + 62
  const H = steps.length * rowH + 4

  const toX = (v: number) => labelW + ((v - min) / range) * barArea

  const colorFor = (kind: WaterfallStep['kind']) => {
    switch (kind) {
      case 'start':
        return 'var(--accent)'
      case 'fee':
        return 'var(--down)'
      case 'cost':
        return 'var(--warn)'
      case 'risk':
        return 'var(--sma7)'
      case 'result':
        return 'var(--up)'
    }
  }

  let prevBalance = 0

  return (
    <svg viewBox={`0 0 ${chartW} ${H}`} className="w-full" role="img" aria-label="Fee decomposition waterfall">
      {steps.map((s, i) => {
        const y = i * rowH + 4
        const isConnector = s.kind !== 'start' && s.kind !== 'result'
        let x1: number
        let x2: number

        if (s.kind === 'start' || s.kind === 'result') {
          x1 = toX(0)
          x2 = toX(s.balance)
        } else {
          x1 = toX(Math.min(prevBalance, s.balance))
          x2 = toX(Math.max(prevBalance, s.balance))
        }

        const barY = y + 3
        const barH = rowH - 11
        const width = Math.max(1.5, x2 - x1)
        const fill = colorFor(s.kind)

        const el = (
          <g key={s.key}>
            {isConnector && (
              <line
                x1={toX(prevBalance)}
                y1={y - rowH + 4 + (rowH - 11) / 2 + 3}
                x2={toX(prevBalance)}
                y2={barY + barH / 2}
                stroke="var(--border-strong)"
                strokeWidth={0.5}
                strokeDasharray="1 2"
              />
            )}
            <rect
              x={x1}
              y={barY}
              width={width}
              height={barH}
              fill={fill}
              opacity={s.kind === 'result' || s.kind === 'start' ? 0.9 : 0.65}
              rx={1}
            />
            <text x={labelW - 6} y={barY + barH / 2 + 3} textAnchor="end" fontSize={8.5} className="fill-muted-foreground uppercase font-mono">
              {s.label}
            </text>
            <text
              x={labelW + barArea + 6}
              y={barY + barH / 2 + 3}
              fontSize={8.5}
              className={`tnum font-mono ${
                s.kind === 'fee' || s.kind === 'risk'
                  ? 'fill-down font-medium'
                  : s.kind === 'cost'
                    ? 'fill-warn font-medium'
                    : 'fill-foreground font-semibold'
              }`}
            >
              {s.kind === 'start' || s.kind === 'result' ? usd(s.balance, { compact: true }) : signedUsd(s.delta)}
            </text>
          </g>
        )
        prevBalance = s.balance
        return el
      })}
    </svg>
  )
}

function HurdleGauge({ roi, hurdle }: { roi: number; hurdle: number }) {
  const lo = Math.min(-10, roi - 5)
  const hi = Math.max(hurdle + 10, roi + 5, 20)
  const range = hi - lo
  const posOf = (v: number) => Math.min(100, Math.max(0, ((v - lo) / range) * 100))

  const roiPos = posOf(roi)
  const hurdlePos = posOf(hurdle)
  const zeroPos = posOf(0)
  const clears = roi >= hurdle

  return (
    <div className="relative h-2.5 rounded-full bg-surface-2">
      <div className="absolute inset-y-0 w-px bg-border-strong" style={{ left: `${zeroPos}%` }} />
      <div
        className={`absolute inset-y-0 rounded-full ${clears ? 'bg-up/60' : roi >= 0 ? 'bg-warn/60' : 'bg-down/60'}`}
        style={{ left: `${Math.min(zeroPos, roiPos)}%`, width: `${Math.abs(roiPos - zeroPos)}%` }}
      />
      <div className="absolute -top-0.5 -bottom-0.5 w-0.5 bg-accent" style={{ left: `${hurdlePos}%` }} title="Hurdle" />
      <div
        className={`absolute top-1/2 h-3.5 w-1 -translate-y-1/2 rounded-full ${clears ? 'bg-up' : roi >= 0 ? 'bg-warn' : 'bg-down'}`}
        style={{ left: `calc(${roiPos}% - 2px)` }}
      />
    </div>
  )
}

function VerdictCell({ label, value, tone, big }: { label: string; value: string; tone: string; big?: boolean }) {
  return (
    <div className="rounded-sm border border-border/60 bg-surface/50 px-2 py-1.5">
      <div className="text-[9px] uppercase text-dim">{label}</div>
      <div className={`tnum font-semibold ${tone} ${big ? 'text-[15px]' : 'text-[12px]'}`}>{value}</div>
    </div>
  )
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  prefix = '',
  suffix = '',
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  prefix?: string
  suffix?: string
  onChange: (v: number) => void
}) {
  return (
    <label className="mb-2 block">
      <div className="mb-0.5 flex items-center justify-between text-[10px]">
        <span className="uppercase text-dim">{label}</span>
        <span className="tnum font-bold text-foreground">
          {prefix}
          {value.toFixed(step < 1 ? 2 : 0)}
          {suffix}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1 w-full cursor-pointer appearance-none rounded-full bg-surface-2 accent-accent"
        aria-label={label}
      />
    </label>
  )
}