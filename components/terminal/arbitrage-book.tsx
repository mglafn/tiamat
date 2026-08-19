// components/terminal/arbitrage-book.tsx
'use client'

import { useEffect, useMemo, useRef } from 'react'
import { ArrowUp, Download, Layers, Sparkles, Star } from 'lucide-react'
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
  stagedUuids: Set<string>
  onToggleStage: (uuid: string) => void
}

export function ArbitrageBook({
  minSpread,
  setMinSpread,
  finish,
  setFinish,
  selectedUuid,
  selectedFinish,
  onSelect,
  stagedUuids,
  onToggleStage,
}: ArbitrageBookProps) {
  const { rows } = useArbitrage(minSpread, finish)
  const catalog = useCatalog()
  const listRef = useRef<HTMLDivElement>(null)

  const maxSpreadPct = useMemo(() => {
    if (rows.length === 0) return 1
    return Math.max(1, ...rows.map((r) => r.spread_pct ?? 0))
  }, [rows])

  const selectedIndex = useMemo(
    () =>
      rows.findIndex(
        (r) => r.uuid === selectedUuid && (!selectedFinish || r.finish === selectedFinish)
      ),
    [rows, selectedUuid, selectedFinish]
  )

  const stagedCount = stagedUuids.size
  const stagedRows = useMemo(() => rows.filter((r) => stagedUuids.has(r.uuid)), [rows, stagedUuids])

  const stagedBasis = useMemo(
    () => stagedRows.reduce((acc, r) => acc + (r.tcg_price || 0), 0),
    [stagedRows]
  )

  const stagedExpectedPayout = useMemo(
    () => stagedRows.reduce((acc, r) => acc + (r.ck_price || 0) * 1.3, 0),
    [stagedRows]
  )

  const blendedROI = useMemo(() => {
    if (stagedBasis <= 0) return 0
    return ((stagedExpectedPayout - stagedBasis) / stagedBasis) * 100
  }, [stagedBasis, stagedExpectedPayout])

  useEffect(() => {
    if (!selectedUuid && rows.length > 0) {
      onSelect(rows[0].uuid, rows[0].finish)
    }
  }, [rows, selectedUuid, onSelect])

  // Vim keyboard navigation (J/K cycle, Space stage/arm, Enter trigger)
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

      if (e.code === 'Space') {
        e.preventDefault()
        const currentUuid = rows[selectedIndex]?.uuid
        if (currentUuid) {
          onToggleStage(currentUuid)
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [rows, selectedIndex, onSelect, onToggleStage])

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(
      `[data-uuid="${selectedUuid}"][data-finish="${selectedFinish}"]`
    )
    el?.scrollIntoView({ block: 'nearest' })
  }, [selectedUuid, selectedFinish])

  const handleExportCSV = () => {
    if (stagedUuids.size === 0) return
    const headers = ['UUID', 'Name', 'Set', 'Finish', 'TCG_Price', 'CK_Buylist', 'Spread_USD', 'Spread_Pct']
    const csvLines = stagedRows.map((r) =>
      [
        r.uuid,
        `"${r.name || 'Unknown'}"`,
        r.set_code || 'OTC',
        r.finish,
        r.tcg_price,
        r.ck_price,
        r.price_spread,
        r.spread_pct,
      ].join(',')
    )

    const blob = new Blob([[headers.join(','), ...csvLines].join('\n')], {
      type: 'text/csv;charset=utf-8;',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `execution_blotter_${new Date().toISOString().split('T')[0]}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section className="relative flex h-full min-h-0 flex-col border-r border-border-strong bg-panel" aria-label="Market spread order book">
      {/* Book Header */}
      <div className="flex items-center justify-between border-b border-border-strong bg-surface px-3 py-1.5">
        <div className="flex items-center gap-2">
          <Layers className="h-3.5 w-3.5 text-accent" />
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-foreground">Market Spread Book</h2>
        </div>
        <span className="tnum font-mono text-[10px] text-dim">{rows.length} PAIRS</span>
      </div>

      {/* Filter Bars */}
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
                  minSpread === s
                    ? 'bg-accent font-semibold text-accent-foreground'
                    : 'text-muted-foreground hover:bg-surface-2'
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
                  finish === f
                    ? 'bg-accent font-semibold text-accent-foreground'
                    : 'text-muted-foreground hover:bg-surface-2'
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Column Headers */}
      <div className="grid grid-cols-[auto_1fr_auto_auto_auto_auto] gap-2 border-b border-border bg-surface/30 px-3 py-1 text-[10px] uppercase text-dim">
        <span className="w-7 text-center">ORD</span>
        <span>SKU / Asset</span>
        <span className="w-14 text-right">ASK (TCG)</span>
        <span className="w-14 text-right">BID (CK)</span>
        <span className="w-12 text-right">SPR%</span>
        <span className="w-4 text-center">★</span>
      </div>

      {/* Virtualized/Scrollable Pair List */}
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
          const isStaged = stagedUuids.has(r.uuid)
          const hot = r.spread_pct >= 25.0
          const spreadBarPct = Math.min(100, Math.max(2, (r.spread_pct / maxSpreadPct) * 100))

          return (
            <button
              key={`${r.uuid}-${r.finish}-${i}`}
              type="button"
              data-uuid={r.uuid}
              data-finish={r.finish}
              onClick={() => onSelect(r.uuid, r.finish)}
              className={`relative grid w-full grid-cols-[auto_1fr_auto_auto_auto_auto] items-center gap-2 border-b border-border/40 px-3 py-1 text-left font-mono text-[11px] transition-colors ${
                selected
                  ? 'bg-accent/15 ring-1 ring-inset ring-accent/50'
                  : 'hover:bg-surface-2/70'
              }`}
            >
              {/* Proportional Depth Bar Tint */}
              <span
                className="pointer-events-none absolute inset-y-0 left-0 bg-up/4 border-r border-up/25 transition-all duration-200"
                style={{ width: `${spreadBarPct}%` }}
                aria-hidden
              />

              {/* EMS-Style Order Arming Micro-Toggle */}
              <span
                onClick={(e) => {
                  e.stopPropagation()
                  onToggleStage(r.uuid)
                }}
                title={isStaged ? "Disarm Order" : "Arm Order for Execution"}
                className={`relative z-10 flex h-3.5 w-7 items-center justify-center rounded-[2px] font-mono text-[8px] font-bold uppercase tracking-wider transition-all select-none cursor-pointer ${
                  isStaged
                    ? 'border border-accent bg-accent text-accent-foreground shadow-[0_0_6px_rgba(74,222,128,0.3)]'
                    : 'border border-border-strong bg-surface/80 text-dim hover:border-accent/60 hover:text-accent'
                }`}
              >
                {isStaged ? 'ARM' : '+'}
              </span>

              <span className="relative truncate">
                <span className={selected ? 'font-semibold text-accent' : 'text-foreground'}>{name}</span>
                {setCode && <span className="ml-1 text-dim">({setCode})</span>}
                {r.finish === 'foil' && <span className="ml-1.5 rounded bg-warn/15 px-1 py-0.2 text-[8.5px] font-bold text-warn">FOIL</span>}
                {r.finish === 'etched' && <span className="ml-1.5 rounded bg-accent/15 px-1 py-0.2 text-[8.5px] font-bold text-accent">ETCH</span>}
              </span>
              <span className="tnum relative w-14 text-right text-muted-foreground">{usd(r.tcg_price, { compact: true })}</span>
              <span className="tnum relative w-14 text-right font-medium text-foreground">{usd(r.ck_price, { compact: true })}</span>
              <span className={`tnum relative w-12 text-right ${r.spread_pct >= 0 ? 'font-semibold text-up' : 'text-down'}`}>
                {pct(r.spread_pct)}
              </span>
              <span className="relative flex w-4 justify-center">
                {hot ? (
                  <Star className="h-3 w-3 fill-warn text-warn" />
                ) : (
                  <ArrowUp className="h-3 w-3 text-up opacity-70" />
                )}
              </span>
            </button>
          )
        })}
      </div>

      {/* Slide-Up Institutional Execution Blotter HUD */}
      {stagedCount > 0 && (
        <div className="border-t border-accent/60 bg-surface-2 px-3 py-2 shadow-2xl">
          <div className="mb-1.5 flex items-center justify-between text-[10px] font-mono">
            <span className="flex items-center gap-1.5 font-semibold uppercase text-accent">
              <Sparkles className="h-3 w-3" />
              <span>[{stagedCount}] Staged Execution Blotter</span>
            </span>
            <span className="text-dim">
              Blended ROI: <span className={`font-bold ${blendedROI >= 10 ? 'text-up' : 'text-warn'}`}>{pct(blendedROI)}</span>
            </span>
          </div>
          <div className="flex items-center justify-between font-mono text-[10px]">
            <div className="flex items-center gap-2 text-dim">
              <span>Landed Basis: <strong className="text-foreground">{usd(stagedBasis, { compact: true })}</strong></span>
              <span>·</span>
              <span>Exp. Liquidation: <strong className="text-foreground">{usd(stagedExpectedPayout, { compact: true })}</strong></span>
            </div>
            <button
              type="button"
              onClick={handleExportCSV}
              className="flex items-center gap-1 rounded-sm border border-accent bg-accent/20 px-2.5 py-0.5 text-[9.5px] font-semibold text-accent transition-colors hover:bg-accent hover:text-accent-foreground"
            >
              <Download className="h-3 w-3" />
              <span>Export Blotter</span>
            </button>
          </div>
        </div>
      )}

      {/* Permanent Navigation Hint Footer */}
      {stagedCount === 0 && (
        <div className="flex h-7 shrink-0 items-center justify-between border-t border-border-strong bg-surface px-3 text-[9.5px] uppercase text-dim">
          <span>
            <kbd className="text-muted-foreground">J</kbd>/<kbd className="text-muted-foreground">K</kbd> Select ·{' '}
            <kbd className="text-muted-foreground">SPC</kbd> Arm Order
          </span>
          <span className="font-mono">Direct/SYP Active</span>
        </div>
      )}
    </section>
  )
}