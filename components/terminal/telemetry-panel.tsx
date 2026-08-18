'use client'

import { useMemo, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { useForecast, useSummary, usePrintings } from '@/lib/hooks'
import { runEconomics, type EconInputs, type WaterfallStep } from '@/lib/economics'
import { usd, pct, signedUsd, shortUuid } from '@/lib/format'
import type { CardVariant } from '@/lib/types'

interface TelemetryPanelProps {
  uuid: string | null
  selectedFinish?: string
  onSelectUuid?: (uuid: string) => void
}

export function TelemetryPanel({ uuid, selectedFinish = 'normal', onSelectUuid }: TelemetryPanelProps) {
  const { data: summary } = useSummary(uuid)
  const { data: forecast } = useForecast(uuid, 'tcgplayer', selectedFinish)
  const { printings } = usePrintings(uuid)

  // Interactive assumption parameters driving the waterfall model.
  const [pro, setPro] = useState(true)
  const [hurdle, setHurdle] = useState(10)
  const [taxRate, setTaxRate] = useState(7.5)
  const [freight, setFreight] = useState(0.09)
  const [kappa, setKappa] = useState(98.5)

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

  const isDeadZone = forecast?.is_dead_zone_clamped || (econ && econ.exitPrice >= 2.5 && econ.exitPrice <= 2.67)

  return (
    <section className="flex min-h-0 flex-col border-l border-border-strong bg-panel" aria-label="Unit economics and execution telemetry">
      <div className="flex items-center justify-between border-b border-border-strong bg-surface px-3 py-1.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-foreground">Unit Economics</h2>
        {econ && (
          <span className={`tnum text-[10px] font-semibold ${econ.clearsHurdle ? 'text-up' : 'text-down'}`}>
            {econ.clearsHurdle ? 'CLEARS HURDLE' : 'BELOW HURDLE'}
          </span>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {!uuid && <p className="p-3 text-[11px] text-dim">No asset selected.</p>}

        {uuid && (
          <>
            {/* SKU header */}
            <div className="border-b border-border/60 bg-surface/40 p-3">
              <div className="flex items-center justify-between text-[10px] uppercase text-dim">
                <span>Selected SKU</span>
                {collectorNum && <span className="font-mono text-dim">{collectorNum}</span>}
              </div>
              <div className="mt-0.5 text-pretty text-[13px] font-medium text-accent">{name}</div>
              <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-[10px]">
                <span className="text-dim">
                  Finish <span className="capitalize text-foreground">{selectedFinish}</span>
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
              <div className="m-3 rounded-sm border border-warn/30 bg-warn/5 p-3">
                <div className="flex items-center justify-between text-[10px] uppercase">
                  <span className="font-semibold text-warn">Execution Halted</span>
                  <span className="font-mono text-[9px] text-dim">CODE: ILLIQUID</span>
                </div>
                <p className="mt-1 text-[10px] leading-relaxed text-dim">
                  Zero active order book depth on tracked marketplaces. Automated Direct/SYP fulfillment and margin routing are offline for this variant.
                </p>
              </div>
            ) : (
              <>
                {/* Waterfall chart */}
                <div className="border-b border-border/60 p-3">
                  <div className="mb-2 flex items-center justify-between text-[10px] uppercase text-dim">
                    <span>Fee Decomposition Waterfall</span>
                    <span className="tnum text-warn">{econ.feeLoadPct.toFixed(1)}% load</span>
                  </div>
                  <Waterfall steps={econ.steps} />
                </div>

                {/* Dead-zone fee cliff notice */}
                {isDeadZone && (
                  <div className="mx-3 mt-3 flex items-start gap-2 rounded-sm border border-warn/40 bg-warn/10 p-2 text-[10px] text-warn">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warn" />
                    <div>
                      <strong>Fee-Cliff Clamped:</strong> Target price was in the [$2.50, $2.67] dead zone. Exit pegged to $2.49 to optimize net margin.
                    </div>
                  </div>
                )}

                {/* Verdict block */}
                <div className="border-b border-border/60 p-3">
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

                  {/* Hurdle gauge */}
                  <div className="mt-3">
                    <div className="mb-1 flex items-center justify-between text-[9px] uppercase text-dim">
                      <span>ROI vs Hurdle</span>
                      <span className="tnum">
                        {pct(econ.netRoiPct)} / {hurdle.toFixed(0)}%
                      </span>
                    </div>
                    <HurdleGauge roi={econ.netRoiPct} hurdle={hurdle} />
                    <div className="mt-1.5 flex items-center justify-between text-[9px] text-dim">
                      <span>Breakeven exit <span className="tnum text-muted-foreground">{usd(econ.breakevenExit, { compact: true })}</span></span>
                      <span>Gross margin <span className="tnum text-muted-foreground">{pct(econ.grossMarginPct, false)}</span></span>
                    </div>
                  </div>
                </div>

                {/* Interactive assumptions */}
                <div className="border-b border-border/60 p-3">
                  <div className="mb-2 text-[10px] uppercase text-dim">Assumptions</div>

                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-[10px] uppercase text-dim">Seller Tier</span>
                    <div className="flex overflow-hidden rounded-sm border border-border text-[10px]">
                      <button
                        type="button"
                        onClick={() => setPro(true)}
                        className={`px-2 py-0.5 transition-colors ${pro ? 'bg-accent font-semibold text-accent-foreground' : 'text-dim hover:text-muted-foreground'}`}
                      >
                        PRO
                      </button>
                      <button
                        type="button"
                        onClick={() => setPro(false)}
                        className={`px-2 py-0.5 transition-colors ${!pro ? 'bg-accent font-semibold text-accent-foreground' : 'text-dim hover:text-muted-foreground'}`}
                      >
                        NON-PRO
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

            {/* Available printings */}
            {printings.length > 0 && (
              <div className="p-3">
                <div className="mb-1.5 flex items-center justify-between text-[10px] uppercase text-dim">
                  <span>Available Printings</span>
                  <span className="tnum">{printings.length} variants</span>
                </div>
                <div className="max-h-40 divide-y divide-border/40 overflow-y-auto rounded-sm border border-border bg-surface/60">
                  {printings.map((p: CardVariant, i: number) => {
                    const isActive = p.uuid === uuid
                    const hasPrice = p.floor_price != null && p.floor_price > 0
                    return (
                      <button
                        key={`${p.uuid}-${p.set_code}-${i}`}
                        type="button"
                        onClick={() => onSelectUuid?.(p.uuid)}
                        className={`flex w-full items-center justify-between px-2.5 py-1.5 text-left text-[11px] transition-all ${
                          isActive
                            ? 'border-l-2 border-accent bg-accent/20 font-semibold text-accent'
                            : hasPrice
                              ? 'text-foreground hover:bg-surface-2'
                              : 'text-dim opacity-50 hover:bg-surface-2/40 hover:opacity-90'
                        }`}
                      >
                        <div className="flex items-center gap-2 truncate">
                          <span className="font-mono text-[10px] text-dim">{p.collector_number ? `#${p.collector_number}` : '—'}</span>
                          <span className="font-semibold">{p.set_code}</span>
                        </div>
                        {hasPrice ? (
                          <span className="tnum font-mono text-[11px] font-medium text-foreground">{usd(p.floor_price, { compact: true })}</span>
                        ) : (
                          <span className="rounded-sm border border-border/60 bg-surface-2 px-1 py-0.5 font-mono text-[9px] uppercase tracking-wider text-dim">
                            UNQUOTED
                          </span>
                        )}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}

/** Bridge waterfall chart — each fee is a floating bar from the running balance. */
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
          // Floating bar between prior balance and new balance.
          x1 = toX(Math.min(prevBalance, s.balance))
          x2 = toX(Math.max(prevBalance, s.balance))
        }
        const barY = y + 3
        const barH = rowH - 11
        const width = Math.max(1, x2 - x1)
        const fill = colorFor(s.kind)

        const el = (
          <g key={s.key}>
            {/* Connector guide from previous balance */}
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
              opacity={s.kind === 'result' || s.kind === 'start' ? 0.85 : 0.6}
              rx={1}
            />
            <text x={labelW - 6} y={barY + barH / 2 + 3} textAnchor="end" fontSize={8.5} className="fill-muted-foreground uppercase">
              {s.label}
            </text>
            <text
              x={labelW + barArea + 6}
              y={barY + barH / 2 + 3}
              fontSize={8.5}
              className={`tnum ${
                s.kind === 'fee' || s.kind === 'risk'
                  ? 'fill-down'
                  : s.kind === 'cost'
                    ? 'fill-warn'
                    : 'fill-foreground'
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
      {/* Zero baseline */}
      <div className="absolute inset-y-0 w-px bg-border-strong" style={{ left: `${zeroPos}%` }} />
      {/* ROI fill */}
      <div
        className={`absolute inset-y-0 rounded-full ${clears ? 'bg-up/50' : roi >= 0 ? 'bg-warn/50' : 'bg-down/50'}`}
        style={{ left: `${Math.min(zeroPos, roiPos)}%`, width: `${Math.abs(roiPos - zeroPos)}%` }}
      />
      {/* Hurdle target marker */}
      <div className="absolute -top-0.5 -bottom-0.5 w-0.5 bg-accent" style={{ left: `${hurdlePos}%` }} title="Hurdle" />
      {/* Active ROI marker */}
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
        <span className="tnum text-foreground">
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