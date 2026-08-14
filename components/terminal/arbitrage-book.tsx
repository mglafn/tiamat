"use client"

import { useEffect, useMemo, useRef } from "react"
import { ArrowUp, Star } from "lucide-react"
import { useArbitrage, useCatalog } from "@/lib/hooks"
import { usd, pct, shortUuid } from "@/lib/format"

const SPREAD_OPTIONS = [2.5, 5, 10, 20]
const FINISH_OPTIONS = ["all", "normal", "foil"] as const

export function ArbitrageBook({
  minSpread,
  setMinSpread,
  finish,
  setFinish,
  selectedUuid,
  onSelect,
}: {
  minSpread: number
  setMinSpread: (n: number) => void
  finish: string
  setFinish: (f: string) => void
  selectedUuid: string | null
  onSelect: (uuid: string) => void
}) {
  const { rows, isLoading } = useArbitrage(minSpread, finish)
  const catalog = useCatalog()
  const listRef = useRef<HTMLDivElement>(null)

  const selectedIndex = useMemo(() => rows.findIndex((r) => r.uuid === selectedUuid), [rows, selectedUuid])

  // Auto-select the top opportunity when the current selection leaves the list.
  useEffect(() => {
    if (rows.length > 0 && selectedIndex === -1) {
      onSelect(rows[0].uuid)
    }
  }, [rows, selectedIndex, onSelect])

  // J/K vim-style row cycling.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === "INPUT" || tag === "TEXTAREA") return
      if (rows.length === 0) return
      if (e.key === "j" || e.key === "k") {
        e.preventDefault()
        const cur = selectedIndex === -1 ? 0 : selectedIndex
        const next = e.key === "j" ? Math.min(cur + 1, rows.length - 1) : Math.max(cur - 1, 0)
        onSelect(rows[next].uuid)
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [rows, selectedIndex, onSelect])

  // Keep selected row in view.
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-uuid="${selectedUuid}"]`)
    el?.scrollIntoView({ block: "nearest" })
  }, [selectedUuid])

  return (
    <section className="flex min-h-0 flex-col border-r border-border-strong bg-panel" aria-label="Arbitrage order book">
      <div className="flex items-center justify-between border-b border-border-strong bg-surface px-3 py-1.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-foreground">Arbitrage Order Book</h2>
        <span className="tnum text-[10px] text-dim">{rows.length} PAIRS</span>
      </div>

      {/* Filters */}
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
                  minSpread === s ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-surface-2"
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
                  finish === f ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-surface-2"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Column header */}
      <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-2 border-b border-border bg-surface/30 px-3 py-1 text-[10px] uppercase text-dim">
        <span>SKU / Name</span>
        <span className="w-14 text-right">TCG</span>
        <span className="w-14 text-right">CK</span>
        <span className="w-12 text-right">SPR%</span>
        <span className="w-6 text-center">ST</span>
      </div>

      {/* Rows */}
      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto">
        {isLoading && rows.length === 0 && (
          <div className="p-3 text-[11px] text-dim">Streaming order book…</div>
        )}
        {rows.map((r) => {
          const meta = catalog.get(r.uuid)
          const name = meta?.name ?? shortUuid(r.uuid)
          const selected = r.uuid === selectedUuid
          const hot = r.spread_pct >= 25
          return (
            <button
              key={r.uuid}
              type="button"
              data-uuid={r.uuid}
              onClick={() => onSelect(r.uuid)}
              className={`grid w-full grid-cols-[1fr_auto_auto_auto_auto] items-center gap-2 border-b border-border/50 px-3 py-1 text-left text-[11px] transition-colors ${
                selected ? "bg-accent/15 ring-1 ring-inset ring-accent/50" : "hover:bg-surface-2/60"
              }`}
            >
              <span className="truncate">
                <span className={selected ? "text-accent" : "text-foreground"}>{name}</span>
                {meta?.set_code && <span className="ml-1 text-dim">{meta.set_code}</span>}
              </span>
              <span className="tnum w-14 text-right text-muted-foreground">{usd(r.tcg_price, { compact: true })}</span>
              <span className="tnum w-14 text-right text-foreground">{usd(r.ck_price, { compact: true })}</span>
              <span className={`tnum w-12 text-right ${r.spread_pct >= 0 ? "text-up" : "text-down"}`}>
                {pct(r.spread_pct)}
              </span>
              <span className="flex w-6 justify-center">
                {hot ? (
                  <Star className="h-3 w-3 fill-warn text-warn" aria-label="Hot spread" />
                ) : (
                  <ArrowUp className="h-3 w-3 text-up" aria-label="Upward spread" />
                )}
              </span>
            </button>
          )
        })}
      </div>

      <div className="border-t border-border-strong bg-surface px-3 py-1 text-[10px] uppercase text-dim">
        <kbd className="text-muted-foreground">J</kbd>/<kbd className="text-muted-foreground">K</kbd> cycle rows · live inference
      </div>
    </section>
  )
}
