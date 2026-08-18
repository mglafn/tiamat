'use client'

import { useEffect, useMemo, useRef } from 'react'
import { ArrowUp, Star } from 'lucide-react'
import { useArbitrage, useCatalog } from '@/lib/hooks'
import { usd, pct, shortUuid } from '@/lib/format'

const SPREAD_OPTIONS = [0, 2.5, 5, 10, 20]
const FINISH_OPTIONS = ['all', 'normal', 'foil', 'etched'] as const

interface ArbitrageBookProps {
  minSpread: number
  setMinSpread: (n: number) => void
  finish: string
  setFinish: (f: string) => void
  selectedUuid: string | null
  selectedFinish?: string
  onSelect: (uuid: string, rowFinish?: string) => void
}

export function ArbitrageBook({
  minSpread,
  setMinSpread,
  finish,
  setFinish,
  selectedUuid,
  selectedFinish,
  onSelect,
}: ArbitrageBookProps) {
  const { rows } = useArbitrage(minSpread, finish)
  const catalog = useCatalog()
  const listRef = useRef<HTMLDivElement>(null)

  // Max spread percentage for normalizing the inline green depth bars
  const maxSpreadPct = useMemo(() => {
    if (rows.length === 0) return 1
    return Math.max(1, ...rows.map((r) => r.spread_pct ?? 0))
  }, [rows])

  const selectedIndex = useMemo(
    () => rows.findIndex((r) => r.uuid === selectedUuid && (!selectedFinish || r.finish === selectedFinish)),
    [rows, selectedUuid, selectedFinish]
  )

  // Default selection to top spread opportunity
  useEffect(() => {
    if (!selectedUuid && rows.length > 0) {
      onSelect(rows[0].uuid, rows[0].finish)
    }
  }, [rows, selectedUuid, onSelect])

  // Vim-style J/K navigation across order book rows
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (rows.length === 0) return

      const key = e.key.toLowerCase()
      if (key === 'j' || key === 'k') {
        e.preventDefault()
        const cur = selectedIndex === -1 ? 0 : selectedIndex
        const next = key === 'j' ? Math.min(cur + 1, rows.length - 1) : Math.max(cur - 1, 0)
        onSelect(rows[next].uuid, rows[next].finish)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [rows, selectedIndex, onSelect])

  // Keep active selection in view
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(
      `[data-uuid="${selectedUuid}"][data-finish="${selectedFinish}"]`
    )
    el?.scrollIntoView({ block: 'nearest' })
  }, [selectedUuid, selectedFinish])

  return (
    <section className="flex h-full min-h-0 flex-col border-r border-border-strong bg-panel" aria-label="Arbitrage order book">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border-strong bg-surface px-3 py-1.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-foreground">Arbitrage Order Book</h2>
        <span className="tnum text-[10px] text-dim">{rows.length} PAIRS</span>
      </div>

      {/* Filter toolbar */}
      <div className="flex flex-wrap items-center gap-3 border-b border-border bg-surface/50 px-3 py-1.5 text-[10px] uppercase">
        <div className="flex items-center gap-1.5">
          <span className="text-dim">Min Spread</span>
          <div className="flex overflow-hidden rounded-sm border border-border">
            {SPREAD_OPTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setMinSpread(s)}
                className={`tnum px-1.5 py-0.5 transition-colors ${
                  minSpread === s ? 'bg-accent font-semibold text-accent-foreground' : 'text-muted-foreground hover:bg-surface-2'
                }`}
              >
                ${s}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-dim">Finish</span>
          <div className="flex overflow-hidden rounded-sm border border-border">
            {FINISH_OPTIONS.map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFinish(f)}
                className={`px-1.5 py-0.5 transition-colors ${
                  finish === f ? 'bg-accent font-semibold text-accent-foreground' : 'text-muted-foreground hover:bg-surface-2'
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Table columns */}
      <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-2 border-b border-border bg-surface/30 px-3 py-1 text-[10px] uppercase text-dim">
        <span>SKU / Asset</span>
        <span className="w-14 text-right">TCG</span>
        <span className="w-14 text-right">CK</span>
        <span className="w-12 text-right">SPR%</span>
        <span className="w-6 text-center">ST</span>
      </div>

      {/* Rows */}
      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto">
        {rows.length === 0 && (
          <div className="p-4 text-center text-[11px] leading-relaxed text-dim">
            No cross-vendor spreads matching &gt;= ${minSpread.toFixed(2)}. Adjust the spread hurdle or finish filter.
          </div>
        )}
        {rows.map((r, i) => {
          const meta = catalog.get(r.uuid)
          const name = r.name && r.name !== r.uuid ? r.name : meta?.name ?? shortUuid(r.uuid)
          const setCode = r.set_code ?? meta?.set_code
          const selected = r.uuid === selectedUuid && (!selectedFinish || r.finish === selectedFinish)
          const hot = r.spread_pct >= 25.0

          // Calculate green background depth bar width based on spread percentage
          const spreadBarPct = Math.min(100, Math.max(3, (r.spread_pct / maxSpreadPct) * 100))

          return (
            <button
              key={`${r.uuid}-${r.finish}-${i}`}
              type="button"
              data-uuid={r.uuid}
              data-finish={r.finish}
              onClick={() => onSelect(r.uuid, r.finish)}
              className={`relative grid w-full grid-cols-[1fr_auto_auto_auto_auto] items-center gap-2 border-b border-border/50 px-3 py-1 text-left text-[11px] transition-colors ${
                selected ? 'bg-accent/20 ring-1 ring-inset ring-accent/60' : 'hover:bg-surface-2/60'
              }`}
            >
              {/* Green spread highlight bar */}
              <span
                className="pointer-events-none absolute inset-y-0 left-0 bg-gradient-to-r from-up/25 via-up/10 to-transparent transition-all duration-300"
                style={{ width: `${spreadBarPct}%` }}
                aria-hidden
              />

              <span className="relative truncate">
                <span className={selected ? 'font-medium text-accent' : 'text-foreground'}>{name}</span>
                {setCode && <span className="ml-1 text-dim">({setCode})</span>}
                {r.finish === 'foil' && <span className="ml-1.5 text-[9px] font-semibold text-warn">FOIL</span>}
                {r.finish === 'etched' && <span className="ml-1.5 text-[9px] font-semibold text-accent">ETCHED</span>}
              </span>
              <span className="tnum relative w-14 text-right text-muted-foreground">{usd(r.tcg_price, { compact: true })}</span>
              <span className="tnum relative w-14 text-right font-medium text-foreground">{usd(r.ck_price, { compact: true })}</span>
              <span className={`tnum relative w-12 text-right ${r.spread_pct >= 0 ? 'font-semibold text-up' : 'text-down'}`}>
                {pct(r.spread_pct)}
              </span>
              <span className="relative flex w-6 justify-center">
                {hot ? (
                  <Star className="h-3 w-3 fill-warn text-warn" aria-label="High-spread opportunity" />
                ) : (
                  <ArrowUp className="h-3 w-3 text-up" aria-label="Positive spread" />
                )}
              </span>
            </button>
          )
        })}
      </div>

      <div className="border-t border-border-strong bg-surface px-3 py-1 text-[10px] uppercase text-dim">
        <kbd className="text-muted-foreground">J</kbd>/<kbd className="text-muted-foreground">K</kbd> cycle rows · bar = spread divergence · live temporal asof
      </div>
    </section>
  )
}