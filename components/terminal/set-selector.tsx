"use client"

import { useState, useRef, useEffect, useMemo } from "react"
import { ChevronDown, Check, Search, Layers } from "lucide-react"
import { usePrintings } from "@/lib/hooks"
import { usd } from "@/lib/format"
import type { CardVariant } from "@/lib/types"

interface SetSelectorProps {
  uuid: string | null
  currentSetCode?: string
  currentCollectorNumber?: string | null
  onSelectUuid: (uuid: string) => void
}

export function SetSelector({
  uuid,
  currentSetCode = "—",
  currentCollectorNumber,
  onSelectUuid,
}: SetSelectorProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const [activeIndex, setActiveIndex] = useState(0)
  const popoverRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const { printings = [], isLoading } = usePrintings(uuid)

  // Filter printings by set code or collector number
  const filteredPrintings = useMemo(() => {
    if (!search.trim()) return printings
    const q = search.toLowerCase().trim()
    return printings.filter(
      (p: CardVariant) =>
        p.set_code.toLowerCase().includes(q) ||
        (p.collector_number && p.collector_number.toLowerCase().includes(q))
    )
  }, [printings, search])

  // Reset search and focus input on open
  useEffect(() => {
    if (open) {
      setSearch("")
      setActiveIndex(0)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  // Close when clicking outside
  useEffect(() => {
    if (!open) return
    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [open])

  // Keyboard navigation inside popover
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setOpen(false)
    } else if (e.key === "ArrowDown") {
      e.preventDefault()
      setActiveIndex((prev) => Math.min(prev + 1, Math.max(0, filteredPrintings.length - 1)))
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setActiveIndex((prev) => Math.max(prev - 1, 0))
    } else if (e.key === "Enter") {
      e.preventDefault()
      const selected = filteredPrintings[activeIndex]
      if (selected) {
        onSelectUuid(selected.uuid)
        setOpen(false)
      }
    }
  }

  if (!uuid || (!isLoading && printings.length <= 1)) {
    return (
      <span className="inline-flex items-center gap-1 rounded-[2px] border border-border-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] font-bold text-foreground">
        <span>{currentSetCode}</span>
        {currentCollectorNumber && <span className="text-dim">#{currentCollectorNumber}</span>}
      </span>
    )
  }

  return (
    <div className="relative inline-block" ref={popoverRef}>
      {/* Trigger Button */}
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className={`inline-flex items-center gap-1.5 rounded-[2px] border px-2 py-0.5 font-mono text-[10px] font-semibold transition-all ${
          open
            ? "border-accent bg-accent/20 text-accent shadow-[0_0_8px_rgba(74,222,128,0.2)]"
            : "border-border-strong bg-surface-2 text-accent hover:border-accent/70 hover:bg-surface-3 hover:text-foreground"
        }`}
        title="Switch Card Printing / Set"
        aria-expanded={open}
      >
        <Layers className="h-3 w-3 text-accent" />
        <span className="font-bold">{currentSetCode}</span>
        {currentCollectorNumber && (
          <span className="text-dim font-normal">#{currentCollectorNumber}</span>
        )}
        <span className="rounded bg-surface-3 px-1 py-0.2 text-[8.5px] font-bold text-muted-foreground">
          {printings.length}
        </span>
        <ChevronDown
          className={`h-3 w-3 text-dim transition-transform duration-150 ${
            open ? "rotate-180 text-accent" : ""
          }`}
        />
      </button>

      {/* Popover Menu */}
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 flex w-64 flex-col overflow-hidden rounded-sm border border-border-strong bg-surface shadow-2xl animate-in fade-in zoom-in-95 duration-100">
          {/* Header & Quick Filter */}
          <div className="border-b border-border-strong bg-surface-2 p-1.5">
            <div className="flex items-center gap-1.5 rounded-[2px] border border-border bg-panel px-2 py-1">
              <Search className="h-3 w-3 text-dim" />
              <input
                ref={inputRef}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Filter set (e.g. 7ED, 2ED)…"
                className="w-full bg-transparent font-mono text-[10px] text-foreground outline-none placeholder:text-dim"
              />
              <span className="text-[8.5px] text-dim uppercase tracking-wider font-mono">
                {filteredPrintings.length} Sets
              </span>
            </div>
          </div>

          {/* Printable Variants List */}
          <div ref={listRef} className="max-h-56 min-h-[40px] overflow-y-auto divide-y divide-border/30">
            {filteredPrintings.length === 0 ? (
              <div className="p-3 text-center font-mono text-[10px] text-dim">
                No matching set printings found.
              </div>
            ) : (
              filteredPrintings.map((p: CardVariant, idx: number) => {
                const isSelected = p.uuid === uuid
                const isItemActive = idx === activeIndex
                const hasFloor = p.floor_price != null && p.floor_price > 0

                return (
                  <button
                    key={`${p.uuid}-${p.set_code}-${idx}`}
                    type="button"
                    onMouseEnter={() => setActiveIndex(idx)}
                    onClick={() => {
                      onSelectUuid(p.uuid)
                      setOpen(false)
                    }}
                    className={`flex w-full items-center justify-between px-2.5 py-1.5 text-left font-mono text-[11px] transition-colors ${
                      isSelected
                        ? "border-l-2 border-accent bg-accent/15 text-accent font-semibold"
                        : isItemActive
                          ? "bg-surface-2 text-foreground"
                          : "text-muted-foreground hover:bg-surface-2/60 hover:text-foreground"
                    }`}
                  >
                    <div className="flex items-center gap-2 truncate">
                      {isSelected ? (
                        <Check className="h-3 w-3 text-accent shrink-0" />
                      ) : (
                        <span className="w-3 shrink-0" />
                      )}
                      <span className="font-bold text-foreground">{p.set_code}</span>
                      <span className="text-[10px] text-dim font-normal">
                        {p.collector_number ? `#${p.collector_number}` : "—"}
                      </span>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      {hasFloor ? (
                        <span className="tnum text-[11px] font-medium text-foreground">
                          {usd(p.floor_price, { compact: true })}
                        </span>
                      ) : (
                        <span className="rounded-sm border border-border/40 bg-panel px-1 py-0.2 text-[8px] font-bold text-dim uppercase">
                          UNQUOTED
                        </span>
                      )}
                    </div>
                  </button>
                )
              })
            )}
          </div>

          {/* Footer Shortcuts */}
          <div className="flex items-center justify-between border-t border-border bg-panel px-2 py-1 text-[9px] uppercase tracking-wider text-dim font-mono">
            <span>↑↓ Navigate</span>
            <span>↵ Select</span>
            <span>ESC Close</span>
          </div>
        </div>
      )}
    </div>
  )
}