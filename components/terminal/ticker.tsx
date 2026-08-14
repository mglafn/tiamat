"use client"

import { useMemo } from "react"
import { useArbitrage, useCatalog } from "@/lib/hooks"
import { usd, pct, shortUuid } from "@/lib/format"

export function Ticker() {
  const { rows } = useArbitrage(0, "all")
  const catalog = useCatalog()

  const items = useMemo(() => {
    return rows.slice(0, 16).map((r) => {
      const name = catalog.get(r.uuid)?.name ?? shortUuid(r.uuid)
      const set = catalog.get(r.uuid)?.set_code
      return {
        uuid: r.uuid,
        label: set ? `${name} · ${set}` : name,
        pct: r.spread_pct,
        price: r.ck_price,
      }
    })
  }, [rows, catalog])

  if (items.length === 0) {
    return <div className="h-7 border-b border-border bg-panel" />
  }

  const doubled = [...items, ...items]

  return (
    <div className="relative flex h-7 items-center overflow-hidden border-b border-border bg-panel">
      <span className="z-10 flex h-full shrink-0 items-center border-r border-border-strong bg-surface-2 px-2 text-[10px] font-semibold uppercase tracking-widest text-accent">
        TICKER
      </span>
      <div className="flex animate-ticker whitespace-nowrap">
        {doubled.map((item, i) => (
          <span key={`${item.uuid}-${i}`} className="flex items-center gap-1.5 px-4 text-[11px]">
            <span className="text-muted-foreground">{item.label}</span>
            <span className={item.pct >= 0 ? "text-up" : "text-down"}>{pct(item.pct)}</span>
            <span className="tnum text-dim">{usd(item.price, { compact: true })}</span>
            <span className="text-border-strong">|</span>
          </span>
        ))}
      </div>
    </div>
  )
}
