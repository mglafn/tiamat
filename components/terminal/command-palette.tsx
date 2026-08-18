"use client"

import { useEffect, useRef, useState } from "react"
import { CornerDownLeft, Loader2, Search } from "lucide-react"
import { useSearch } from "@/lib/hooks"
import { usd } from "@/lib/format"

interface CommandPaletteProps {
  open: boolean
  onClose: () => void
  onSelect: (uuid: string, finish?: string) => void
}

export function CommandPalette({
  open,
  onClose,
  onSelect,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("")
  const [debouncedQuery, setDebouncedQuery] = useState("")
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      setQuery("")
      setDebouncedQuery("")
      setActive(0)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  // Debounce input to limit API calls on rapid typing
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedQuery(query)
    }, 250)
    return () => clearTimeout(handler)
  }, [query])

  const { data: results = [], isLoading } = useSearch(debouncedQuery)
  const isDebouncing = query.trim() !== debouncedQuery.trim()
  const isSearching = (isLoading || isDebouncing) && query.trim().length >= 2

  useEffect(() => {
    setActive(0)
  }, [results.length])

  if (!open) return null

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return
    if (e.key === "Escape") {
      onClose()
    } else if (e.key === "ArrowDown") {
      e.preventDefault()
      setActive((a) => Math.min(a + 1, Math.max(0, results.length - 1)))
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setActive((a) => Math.max(a - 1, 0))
    } else if (e.key === "Enter") {
      e.preventDefault()
      const pick = results[active]
      if (pick) {
        onSelect(pick.uuid, pick.finish)
        onClose()
      }
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-background/70 pt-[12vh] backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-md border border-border-strong bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Card search"
      >
        <div className="flex items-center gap-2 border-b border-border-strong px-3">
          {isSearching ? (
            <Loader2 className="h-4 w-4 animate-spin text-accent" />
          ) : (
            <Search className="h-4 w-4 text-dim" />
          )}
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Resolve card name → UUID · e.g. Ragavan, Mox…"
            className="w-full bg-transparent py-3 text-[13px] text-foreground outline-none placeholder:text-dim"
            aria-label="Card name query"
          />
          <kbd className="rounded-sm border border-border bg-panel px-1 py-0.5 text-[10px] text-dim">
            ESC
          </kbd>
        </div>
        <div className="max-h-[52vh] overflow-y-auto">
          {query.trim().length < 2 && (
            <p className="px-3 py-4 text-[11px] text-dim">
              Type at least 2 characters to query /api/v1/search.
            </p>
          )}
          {isSearching && (
            <div className="flex items-center justify-center gap-2 p-6 text-[12px] text-dim">
              <Loader2 className="h-4 w-4 animate-spin text-accent" /> Resolving
              printings across catalog…
            </div>
          )}
          {!isSearching && query.trim().length >= 2 && results.length === 0 && (
            <p className="px-3 py-4 text-[11px] text-dim">
              No printings found for &quot;{query}&quot;.
            </p>
          )}
          {!isSearching &&
            results.map((r, i) => (
              <button
                key={`${r.uuid}-${r.finish}-${i}`}
                type="button"
                onMouseEnter={() => setActive(i)}
                onClick={() => {
                  onSelect(r.uuid, r.finish)
                  onClose()
                }}
                className={`flex w-full items-center gap-3 border-b border-border/40 px-3 py-2 text-left text-[12px] transition-colors ${
                  i === active ? "bg-accent/15" : "hover:bg-surface-2/60"
                }`}
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate">
                    <span
                      className={
                        i === active ? "text-accent" : "text-foreground"
                      }
                    >
                      {r.name}
                    </span>
                    <span className="ml-2 text-dim">{r.set_code}</span>
                    <span className="ml-2 capitalize text-dim">{r.finish}</span>
                  </div>
                </div>
                <span className="tnum shrink-0 text-muted-foreground">
                  {usd(r.floor_price, { compact: true })}
                </span>
                <span className="tnum shrink-0 text-[10px] text-dim">
                  {r.vendor_count}V
                </span>
                {i === active && (
                  <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-accent" />
                )}
              </button>
            ))}
        </div>
        <div className="flex items-center gap-3 border-t border-border-strong bg-panel px-3 py-1.5 text-[10px] uppercase text-dim">
          <span>↑↓ Navigate</span>
          <span>↵ Load asset</span>
          <span className="ml-auto">{results.length} results</span>
        </div>
      </div>
    </div>
  )
}