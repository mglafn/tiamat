'use client'

import { useEffect, useState, useMemo } from 'react'
import {
  Activity,
  Cpu,
  Flame,
  ShieldAlert,
  Sliders,
  TrendingDown,
  TrendingUp,
  X,
} from 'lucide-react'
import { useBacktest } from '@/lib/hooks'
import { usd, pct, signedUsd } from '@/lib/format'
import type { BacktestEquityPoint, BacktestTrade } from '@/lib/types'

interface StrategyLabModalProps {
  open: boolean
  onClose: () => void
}

export function StrategyLabModal({ open, onClose }: StrategyLabModalProps) {
  const [hurdle, setHurdle] = useState<number>(10.0)
  const [tau, setTau] = useState<number>(0.90)
  const [filterMode, setFilterMode] = useState<'exp_roi' | 'win_roi' | 'kelly'>('exp_roi')
  const [sizing, setSizing] = useState<'flat' | 'kelly'>('flat')
  const [activeTab, setActiveTab] = useState<'top' | 'worst' | 'vetoed'>('top')

  const { data: backtest } = useBacktest(hurdle, tau, filterMode, sizing)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  // Chart geometry for dual equity curve
  const chartGeom = useMemo(() => {
    const curve: BacktestEquityPoint[] = backtest?.equity_curve ?? []
    if (curve.length === 0) return null

    const allVals = curve.flatMap((c: BacktestEquityPoint) => [c.active_cum_profit, c.naive_cum_profit])
    const minVal = Math.min(0, ...allVals)
    const maxVal = Math.max(5, ...allVals)
    const pad = (maxVal - minVal) * 0.15 || 5
    const lo = minVal - pad
    const hi = maxVal + pad

    const W = 620
    const H = 160
    const padL = 45
    const padR = 20
    const padT = 15
    const padB = 25

    const plotW = W - padL - padR
    const plotH = H - padT - padB

    const x = (i: number) => padL + (i / Math.max(1, curve.length - 1)) * plotW
    const y = (val: number) => padT + (1 - (val - lo) / Math.max(0.001, hi - lo)) * plotH
    const zeroY = y(0)

    const activeLine = curve
      .map((c: BacktestEquityPoint, i: number) => `${x(i).toFixed(1)},${y(c.active_cum_profit).toFixed(1)}`)
      .join(' ')
    const naiveLine = curve
      .map((c: BacktestEquityPoint, i: number) => `${x(i).toFixed(1)},${y(c.naive_cum_profit).toFixed(1)}`)
      .join(' ')

    return { W, H, padL, padR, padT, padB, plotW, plotH, x, y, zeroY, activeLine, naiveLine, curve }
  }, [backtest])

  if (!open) return null

  const summary = backtest?.summary
  const ablation = backtest?.ablation

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4 backdrop-blur-md sm:p-6"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="flex h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-lg border border-border-strong bg-surface shadow-2xl font-mono"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex h-11 shrink-0 items-center justify-between border-b border-border-strong bg-panel px-4">
          <div className="flex items-center gap-2">
            <Cpu className="h-4 w-4 text-accent" />
            <span className="text-[12px] font-semibold uppercase tracking-widest text-foreground">
              Strategy Lab · Out-Of-Time Quantitative Backtest Engine
            </span>
            <span className="rounded-[3px] border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-[9px] font-bold text-accent">
              BAYESIAN ABLATION ACTIVE
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex items-center gap-1.5 text-[11px] text-dim transition-colors hover:text-foreground"
          >
            <kbd className="rounded border border-border bg-surface px-1.5 py-0.5 text-[9px]">ESC</kbd>
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Content Body (Grid Layout) */}
        <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[300px_minmax(0,1fr)]">
          {/* Left Panel: Strategy Parameters & Controls */}
          <div className="flex flex-col border-r border-border bg-surface-2/30 p-4">
            <div className="flex items-center justify-between border-b border-border pb-2 text-[11px] font-bold uppercase text-accent">
              <span className="flex items-center gap-1.5">
                <Sliders className="h-3.5 w-3.5" />
                <span>Simulation Parameters</span>
              </span>
            </div>

            <div className="mt-4 space-y-4 text-[11px]">
              {/* ROI Hurdle Slider */}
              <div>
                <div className="flex items-center justify-between text-dim">
                  <span>Net ROI Hurdle</span>
                  <span className="tnum font-bold text-foreground">{hurdle.toFixed(1)}%</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="30"
                  step="1"
                  value={hurdle}
                  onChange={(e) => setHurdle(Number(e.target.value))}
                  className="mt-1.5 h-1 w-full cursor-pointer appearance-none rounded bg-surface-3 accent-accent"
                />
              </div>

              {/* Tau Cutoff Slider */}
              <div>
                <div className="flex items-center justify-between text-dim">
                  <span>Confidence Cutoff (τ)</span>
                  <span className="tnum font-bold text-accent">{tau.toFixed(2)}</span>
                </div>
                <input
                  type="range"
                  min="0.50"
                  max="0.98"
                  step="0.01"
                  value={tau}
                  onChange={(e) => setTau(Number(e.target.value))}
                  className="mt-1.5 h-1 w-full cursor-pointer appearance-none rounded bg-surface-3 accent-accent"
                />
                <span className="text-[9px] text-dim">Stage 1 Mover Gate probability threshold</span>
              </div>

              {/* Filter Mode Toggle */}
              <div>
                <span className="text-dim">Decision Filter Mode</span>
                <div className="mt-1.5 grid grid-cols-3 gap-1 rounded border border-border bg-surface p-0.5 text-[9.5px]">
                  <button
                    type="button"
                    onClick={() => setFilterMode('exp_roi')}
                    className={`rounded py-1 font-semibold ${
                      filterMode === 'exp_roi' ? 'bg-accent text-accent-foreground' : 'text-dim hover:text-foreground'
                    }`}
                  >
                    EXP_ROI
                  </button>
                  <button
                    type="button"
                    onClick={() => setFilterMode('win_roi')}
                    className={`rounded py-1 font-semibold ${
                      filterMode === 'win_roi' ? 'bg-accent text-accent-foreground' : 'text-dim hover:text-foreground'
                    }`}
                  >
                    NAIVE
                  </button>
                  <button
                    type="button"
                    onClick={() => setFilterMode('kelly')}
                    className={`rounded py-1 font-semibold ${
                      filterMode === 'kelly' ? 'bg-accent text-accent-foreground' : 'text-dim hover:text-foreground'
                    }`}
                  >
                    KELLY
                  </button>
                </div>
              </div>

              {/* Sizing Model */}
              <div>
                <span className="text-dim">Position Sizing Allocation</span>
                <div className="mt-1.5 grid grid-cols-2 gap-1 rounded border border-border bg-surface p-0.5 text-[10px]">
                  <button
                    type="button"
                    onClick={() => setSizing('flat')}
                    className={`rounded py-1 font-semibold ${
                      sizing === 'flat' ? 'bg-surface-2 text-foreground' : 'text-dim hover:text-foreground'
                    }`}
                  >
                    FLAT (1 Unit)
                  </button>
                  <button
                    type="button"
                    onClick={() => setSizing('kelly')}
                    className={`rounded py-1 font-semibold ${
                      sizing === 'kelly' ? 'bg-accent text-accent-foreground' : 'text-dim hover:text-foreground'
                    }`}
                  >
                    HALF-KELLY (f*)
                  </button>
                </div>
              </div>
            </div>

            {/* Explanatory Callout */}
            <div className="mt-auto rounded border border-border bg-surface-2/60 p-3 text-[10px] leading-relaxed text-dim">
              <span className="font-bold uppercase text-foreground">Anti-Leakage Partition:</span>
              <p className="mt-1">
                Evaluates out-of-time historical quotes protected by a strict <strong>14-day embargo</strong> from training splits.
              </p>
            </div>
          </div>

          {/* Right Panel: Charts, KPIs & Ablation Ledger */}
          <div className="flex min-h-0 flex-col overflow-y-auto p-4 space-y-4">
            {/* Top Row: Dual Equity Curve & Ablation Card */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.4fr_1fr]">
              {/* Dual Cumulative PnL Curve */}
              <div className="rounded border border-border bg-surface-2/40 p-3">
                <div className="flex items-center justify-between border-b border-border/60 pb-2 text-[11px]">
                  <span className="flex items-center gap-1.5 font-bold uppercase text-foreground">
                    <Activity className="h-3.5 w-3.5 text-accent" />
                    <span>Cumulative PnL Equity Curve (USD)</span>
                  </span>
                  <div className="flex items-center gap-3 text-[9.5px]">
                    <span className="flex items-center gap-1 text-up font-semibold">
                      <span className="h-2 w-2 rounded-full bg-up" />
                      <span>Active (EXP_ROI)</span>
                    </span>
                    <span className="flex items-center gap-1 text-down">
                      <span className="h-2 w-2 rounded-full bg-down" />
                      <span>Naive Baseline</span>
                    </span>
                  </div>
                </div>

                {/* SVG Equity Plot */}
                <div className="mt-2 h-40 w-full">
                  {chartGeom && (
                    <svg viewBox={`0 0 ${chartGeom.W} ${chartGeom.H}`} className="h-full w-full">
                      {/* Zero Benchmark Line */}
                      <line
                        x1={chartGeom.padL}
                        y1={chartGeom.zeroY}
                        x2={chartGeom.W - chartGeom.padR}
                        y2={chartGeom.zeroY}
                        stroke="var(--border-strong)"
                        strokeWidth="1"
                        strokeDasharray="3 3"
                      />
                      {/* Naive Baseline Line */}
                      <polyline
                        points={chartGeom.naiveLine}
                        fill="none"
                        stroke="var(--down)"
                        strokeWidth="1.5"
                        strokeDasharray="4 2"
                        opacity="0.8"
                      />
                      {/* Active Strategy Line */}
                      <polyline
                        points={chartGeom.activeLine}
                        fill="none"
                        stroke="var(--up)"
                        strokeWidth="2.5"
                      />
                      {/* X-Axis Dates */}
                      {chartGeom.curve.map((c: BacktestEquityPoint, i: number) => (
                        <text
                          key={i}
                          x={chartGeom.x(i)}
                          y={chartGeom.H - 5}
                          textAnchor="middle"
                          fontSize="8.5"
                          className="fill-dim font-mono"
                        >
                          {c.date.slice(5)}
                        </text>
                      ))}
                    </svg>
                  )}
                </div>
              </div>

              {/* Counterfactual Alpha Scorecard */}
              <div className="rounded border border-accent/40 bg-accent/5 p-3">
                <div className="flex items-center justify-between border-b border-accent/20 pb-2 text-[11px] font-bold uppercase text-accent">
                  <span className="flex items-center gap-1.5">
                    <Flame className="h-3.5 w-3.5" />
                    <span>Alpha & Capital Preserved</span>
                  </span>
                </div>

                <div className="mt-3 space-y-2 text-[11px]">
                  <div className="flex items-center justify-between">
                    <span className="text-dim">🎯 True Alpha Generated:</span>
                    <span className="tnum font-bold text-up">
                      {signedUsd(ablation?.alpha_cash)} ({pct((ablation?.alpha_roi_bps ?? 0) / 100)})
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-dim">🛡️ Capital Preserved:</span>
                    <span className="tnum font-bold text-foreground">
                      {usd(ablation?.capital_saved)} ({ablation?.capital_saved_pct?.toFixed(1) ?? '0.0'}% saved)
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-dim">🚫 Downside Pruned:</span>
                    <span className="tnum font-bold text-up">
                      {usd(ablation?.vetoed_losses_avoided)} avoided
                    </span>
                  </div>
                  <div className="flex items-center justify-between border-t border-border/60 pt-2 text-[10px]">
                    <span className="text-dim">Win Rate Expansion:</span>
                    <span className="tnum font-bold text-up">
                      {ablation?.naive_win_rate?.toFixed(1) ?? '0.0'}% ➔ {summary?.win_rate?.toFixed(1) ?? '0.0'}%
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Performance KPI Cards */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-center">
              <div className="rounded border border-border bg-surface p-2.5">
                <div className="text-[9.5px] uppercase text-dim">Triggered Trades</div>
                <div className="text-[14px] font-bold text-foreground mt-0.5">
                  {summary?.total_trades ?? 0}{' '}
                  <span className="text-[10px] text-dim">
                    ({summary?.win_trades ?? 0}W/{summary?.loss_trades ?? 0}L)
                  </span>
                </div>
              </div>
              <div className="rounded border border-border bg-surface p-2.5">
                <div className="text-[9.5px] uppercase text-dim">Capital Deployed</div>
                <div className="text-[14px] font-bold text-foreground mt-0.5">{usd(summary?.total_capital)}</div>
              </div>
              <div className="rounded border border-border bg-surface p-2.5">
                <div className="text-[9.5px] uppercase text-dim">Net Realized Profit</div>
                <div className={`text-[14px] font-bold mt-0.5 ${(summary?.total_net_profit ?? 0) >= 0 ? 'text-up' : 'text-down'}`}>
                  {signedUsd(summary?.total_net_profit)}
                </div>
              </div>
              <div className="rounded border border-border bg-surface p-2.5">
                <div className="text-[9.5px] uppercase text-dim">Portfolio Return (ROI)</div>
                <div className={`text-[14px] font-bold mt-0.5 ${(summary?.portfolio_roi ?? 0) >= 0 ? 'text-up' : 'text-down'}`}>
                  {pct(summary?.portfolio_roi)}
                </div>
              </div>
            </div>

            {/* Bottom Tabbed Ledger */}
            <div className="rounded border border-border bg-surface">
              <div className="flex border-b border-border text-[10px] font-semibold uppercase">
                <button
                  type="button"
                  onClick={() => setActiveTab('top')}
                  className={`px-4 py-2 flex items-center gap-1.5 transition-colors ${
                    activeTab === 'top' ? 'border-b-2 border-up bg-surface-2 text-up font-bold' : 'text-dim hover:text-foreground'
                  }`}
                >
                  <TrendingUp className="h-3 w-3" />
                  <span>Top Realized Trades ({backtest?.top_trades?.length ?? 0})</span>
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('worst')}
                  className={`px-4 py-2 flex items-center gap-1.5 transition-colors ${
                    activeTab === 'worst' ? 'border-b-2 border-down bg-surface-2 text-down font-bold' : 'text-dim hover:text-foreground'
                  }`}
                >
                  <TrendingDown className="h-3 w-3" />
                  <span>Drawdowns ({backtest?.worst_trades?.length ?? 0})</span>
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('vetoed')}
                  className={`px-4 py-2 flex items-center gap-1.5 transition-colors ${
                    activeTab === 'vetoed' ? 'border-b-2 border-warn bg-surface-2 text-warn font-bold' : 'text-dim hover:text-foreground'
                  }`}
                >
                  <ShieldAlert className="h-3 w-3" />
                  <span>🛡️ Avoided Traps / Pruned ({backtest?.vetoed_traps?.length ?? 0})</span>
                </button>
              </div>

              {/* Table Body */}
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[11px]">
                  <thead className="border-b border-border bg-surface-2/40 text-[9.5px] uppercase text-dim">
                    <tr>
                      <th className="px-3 py-1.5">Date</th>
                      <th className="px-3 py-1.5">Card / Set</th>
                      <th className="px-3 py-1.5 text-right">Basis</th>
                      <th className="px-3 py-1.5 text-right">Exit Net</th>
                      <th className="px-3 py-1.5 text-right">Pred (Prob)</th>
                      {activeTab === 'vetoed' && <th className="px-3 py-1.5">Why Vetoed</th>}
                      <th className="px-3 py-1.5 text-right">Realized PnL</th>
                      <th className="px-3 py-1.5 text-right">ROI (%)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/40 font-mono">
                    {activeTab === 'top' &&
                      (backtest?.top_trades ?? []).map((t: BacktestTrade, i: number) => (
                        <tr key={i} className="hover:bg-surface-2/50">
                          <td className="px-3 py-1.5 text-dim">{t.price_date}</td>
                          <td className="px-3 py-1.5 font-medium text-foreground">
                            {t.name} ({t.set_code})
                          </td>
                          <td className="px-3 py-1.5 text-right text-dim">{usd(t.basis)}</td>
                          <td className="px-3 py-1.5 text-right font-medium">{usd(t.realized_exit_payout)}</td>
                          <td className="px-3 py-1.5 text-right text-dim">
                            {t.pred_magnitude > 0 ? `+${t.pred_magnitude.toFixed(1)}%` : `${t.pred_magnitude.toFixed(1)}%`} ({(t.move_prob * 100).toFixed(0)}%)
                          </td>
                          <td className="px-3 py-1.5 text-right font-bold text-up">{signedUsd(t.total_profit)}</td>
                          <td className="px-3 py-1.5 text-right font-bold text-up">{pct(t.net_roi_pct)}</td>
                        </tr>
                      ))}

                    {activeTab === 'worst' &&
                      (backtest?.worst_trades ?? []).map((t: BacktestTrade, i: number) => (
                        <tr key={i} className="hover:bg-surface-2/50">
                          <td className="px-3 py-1.5 text-dim">{t.price_date}</td>
                          <td className="px-3 py-1.5 font-medium text-foreground">
                            {t.name} ({t.set_code})
                          </td>
                          <td className="px-3 py-1.5 text-right text-dim">{usd(t.basis)}</td>
                          <td className="px-3 py-1.5 text-right font-medium">{usd(t.realized_exit_payout)}</td>
                          <td className="px-3 py-1.5 text-right text-dim">
                            {t.pred_magnitude > 0 ? `+${t.pred_magnitude.toFixed(1)}%` : `${t.pred_magnitude.toFixed(1)}%`} ({(t.move_prob * 100).toFixed(0)}%)
                          </td>
                          <td className="px-3 py-1.5 text-right font-bold text-down">{signedUsd(t.total_profit)}</td>
                          <td className="px-3 py-1.5 text-right font-bold text-down">{pct(t.net_roi_pct)}</td>
                        </tr>
                      ))}

                    {activeTab === 'vetoed' &&
                      (backtest?.vetoed_traps ?? []).map((t: BacktestTrade, i: number) => (
                        <tr key={i} className="hover:bg-surface-2/50">
                          <td className="px-3 py-1.5 text-dim">{t.price_date}</td>
                          <td className="px-3 py-1.5 font-medium text-foreground">
                            {t.name} ({t.set_code})
                          </td>
                          <td className="px-3 py-1.5 text-right text-dim">{usd(t.basis)}</td>
                          <td className="px-3 py-1.5 text-right font-medium">{usd(t.realized_exit_payout)}</td>
                          <td className="px-3 py-1.5 text-right text-dim">
                            {t.pred_magnitude > 0 ? `+${t.pred_magnitude.toFixed(1)}%` : `${t.pred_magnitude.toFixed(1)}%`} ({(t.move_prob * 100).toFixed(0)}%)
                          </td>
                          <td className="px-3 py-1.5 text-warn font-semibold">{t.veto_reason}</td>
                          <td className="px-3 py-1.5 text-right font-bold text-down">{signedUsd(t.total_profit)}</td>
                          <td className="px-3 py-1.5 text-right font-bold text-down">{pct(t.net_roi_pct)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex h-8 shrink-0 items-center justify-between border-t border-border bg-panel px-4 text-[10px] text-dim">
          <span>
            Out-of-Time Universe: {summary?.test_universe_count?.toLocaleString() ?? 0} rows ({summary?.test_start_date ?? '—'} to {summary?.test_end_date ?? '—'})
          </span>
          <span>TCGplayer Direct / SYP Piecewise Schedule Calibrated</span>
        </div>
      </div>
    </div>
  )
}