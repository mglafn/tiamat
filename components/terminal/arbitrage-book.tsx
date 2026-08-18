"use client"

import { useEffect, useMemo, useRef } from "react"
import { AlertCircle, ArrowUp, Loader2, RefreshCw, Star } from "lucide-react"
import { useArbitrage, useCatalog } from "@/lib/hooks"
import { usd, pct, shortUuid } from "@/lib/format"

const SPREAD_OPTIONS = [0, 2.5, 5, 10, 20]
const FINISH_OPTIONS = ["all", "normal", "foil", "etched"] as const

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
  const { rows, error, isLoading, isValidating } = useArbitrage(minSpread, finish)
  const catalog = useCatalog()
  const listRef = useRef<HTMLDivElement>(null)

  const selectedIndex = useMemo(
    () => rows.findIndex((r) => r.uuid === selectedUuid && (!selectedFinish || r.finish === selectedFinish)),
    [rows, selectedUuid, selectedFinish]
  )

  // Default selection to top spread opportunity on initial load
  useEffect(() => {
    if (!selectedUuid && rows.length > 0) {
      onSelect(rows[0].uuid, rows[0].finish)
    }
  }, [rows, selectedUuid, onSelect])

  // Vim-style J/K navigation across order book rows
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === "INPUT" || tag === "TEXTAREA") return
      if (rows.length === 0) return

      const key = e.key.toLowerCase()
      if (key === "j" || key === "k") {
        e.preventDefault()
        const cur = selectedIndex === -1 ? 0 : selectedIndex
        const next = key === "j" ? Math.min(cur + 1, rows.length - 1) : Math.max(cur - 1, 0)
        onSelect(rows[next].uuid, rows[next].finish)
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [rows, selectedIndex, onSelect])

  // Keep active selection in view during keyboard navigation
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-uuid="${selectedUuid}"][data-finish="${selectedFinish}"]`)
    el?.scrollIntoView({ block: "nearest" })
  }, [selectedUuid, selectedFinish])

  return (
    <section className="flex h-full min-h-0 flex-col border-r border-border-strong bg-panel" aria-label="Arbitrage order book">
      {/* Header & sync state */}
      <div className="flex items-center justify-between border-b border-border-strong bg-surface px-3 py-1.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-foreground">Arbitrage Order Book</h2>
        {error ? (
          <span className="flex items-center gap-1.5 text-[10px] text-down">
            <AlertCircle className="h-3 w-3" /> BROKEN
          </span>
        ) : isLoading && rows.length === 0 ? (
          <span className="flex items-center gap-1.5 text-[10px] text-accent">
            <Loader2 className="h-3 w-3 animate-spin" /> FETCHING
          </span>
        ) : isValidating ? (
          <span className="flex items-center gap-1.5 text-[10px] text-accent">
            <RefreshCw className="h-2.5 w-2.5 animate-spin" /> {rows.length} PAIRS
          </span>
        ) : (
          <span className="tnum text-[10px] text-dim">{rows.length} PAIRS</span>
        )}
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
                  minSpread === s ? "bg-accent text-accent-foreground font-semibold" : "text-muted-foreground hover:bg-surface-2"
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
                  finish === f ? "bg-accent text-accent-foreground font-semibold" : "text-muted-foreground hover:bg-surface-2"
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
        {isLoading && rows.length === 0 && !error && (
          <div className="space-y-1.5 p-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="flex h-6 animate-pulse items-center gap-2 rounded-sm bg-surface-2/60 px-2" />
            ))}
          </div>
        )}
        {error && rows.length === 0 && (
          <div className="p-4 text-center text-[11px] text-down">
            Connection failed. Unable to fetch real-time arbitrage spreads.
          </div>
        )}
        {!isLoading && !error && rows.length === 0 && (
          <div className="p-4 text-center text-[11px] text-dim leading-relaxed">
            No cross-vendor spreads matching &gt;= ${minSpread.toFixed(2)}. Adjust the spread hurdle or finish filter.
          </div>
        )}
        {rows.map((r, i) => {
          const meta = catalog.get(r.uuid)
          const name = r.name && r.name !== r.uuid ? r.name : meta?.name ?? shortUuid(r.uuid)
          const setCode = r.set_code ?? meta?.set_code
          const selected = r.uuid === selectedUuid && (!selectedFinish || r.finish === selectedFinish)
          const hot = r.spread_pct >= 25.0

          return (
            <button
              key={`${r.uuid}-${r.finish}-${i}`}
              type="button"
              data-uuid={r.uuid}
              data-finish={r.finish}
              onClick={() => onSelect(r.uuid, r.finish)}
              className={`grid w-full grid-cols-[1fr_auto_auto_auto_auto] items-center gap-2 border-b border-border/50 px-3 py-1 text-left text-[11px] transition-colors ${
                selected ? "bg-accent/15 ring-1 ring-inset ring-accent/50" : "hover:bg-surface-2/60"
              }`}
            >
              <span className="truncate">
                <span className={selected ? "text-accent font-medium" : "text-foreground"}>{name}</span>
                {setCode && <span className="ml-1 text-dim">({setCode})</span>}
                {r.finish === "foil" && <span className="ml-1.5 text-[9px] font-semibold text-warn">FOIL</span>}
                {r.finish === "etched" && <span className="ml-1.5 text-[9px] font-semibold text-accent">ETCHED</span>}
              </span>
              <span className="tnum w-14 text-right text-muted-foreground">{usd(r.tcg_price, { compact: true })}</span>
              <span className="tnum w-14 text-right text-foreground font-medium">{usd(r.ck_price, { compact: true })}</span>
              <span className={`tnum w-12 text-right ${r.spread_pct >= 0 ? "text-up font-semibold" : "text-down"}`}>
                {pct(r.spread_pct)}
              </span>
              <span className="flex w-6 justify-center">
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
        <kbd className="text-muted-foreground">J</kbd>/<kbd className="text-muted-foreground">K</kbd> cycle rows · live temporal asof
      </div>
    </section>
  )
}