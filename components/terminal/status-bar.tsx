"use client"

import { useEffect, useState } from "react"
import { Search } from "lucide-react"
import { useHealth } from "@/lib/hooks"

function useClock() {
  const [now, setNow] = useState<string>("--:--:--")
  useEffect(() => {
    const tick = () =>
      setNow(
        new Date().toLocaleTimeString("en-GB", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        }),
      )
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])
  return now
}

function Stat({
  label,
  value,
  tone = "default",
}: {
  label: string
  value: string
  tone?: "default" | "up" | "warn" | "down"
}) {
  const toneClass =
    tone === "up"
      ? "text-up"
      : tone === "warn"
        ? "text-warn"
        : tone === "down"
          ? "text-down"
          : "text-foreground"

  return (
    <div className="flex items-center gap-1.5 whitespace-nowrap">
      <span className="text-dim">{label}</span>
      <span className={`tnum ${toneClass}`}>{value}</span>
    </div>
  )
}

export function StatusBar({ onOpenSearch }: { onOpenSearch: () => void }) {
  const { data, isLoading } = useHealth()
  const clock = useClock()

  const live = data?.status === "healthy"
  const isMock = data?.source === "mock"

  return (
    <header className="flex h-9 items-center gap-4 border-b border-border-strong bg-surface px-3 text-[11px] uppercase tracking-wider">
      {/* Engine Live / Degraded Indicator */}
      <div className="flex items-center gap-2">
        <span
          className={`h-2 w-2 rounded-full ${
            isLoading
              ? "bg-dim"
              : live
                ? "bg-up animate-blink"
                : "bg-down"
          }`}
          aria-hidden
        />
        <span className={isLoading ? "text-dim" : live ? "text-up" : "text-down"}>
          {isLoading ? "SYNCING" : live ? "ONLINE" : "DEGRADED"}
        </span>
      </div>

      {/* Verified Backend Engine Status */}
      <div className="hidden items-center gap-4 md:flex">
        <Stat
          label="DuckDB"
          value={data?.db_connected ? "CONNECTED" : "OFFLINE"}
          tone={data?.db_connected ? "up" : "down"}
        />
        <Stat
          label="XGBoost"
          value={data?.model_loaded ? "READY" : "UNLOADED"}
          tone={data?.model_loaded ? "up" : "warn"}
        />
        <Stat
          label="Feed Mode"
          value={isMock ? "MOCK FALLBACK" : "PERSISTENT IPC"}
          tone={isMock ? "warn" : "default"}
        />
      </div>

      {/* Search Trigger */}
      <button
        type="button"
        onClick={onOpenSearch}
        className="ml-auto flex items-center gap-2 rounded-sm border border-border-strong bg-panel px-2.5 py-1 text-dim transition-colors hover:border-accent hover:text-foreground"
        aria-label="Search card catalog"
      >
        <Search className="h-3.5 w-3.5" />
        <span className="hidden normal-case tracking-normal sm:inline">Search Card</span>
        <kbd className="rounded-sm border border-border bg-surface-2 px-1 py-0.5 text-[10px] normal-case text-muted-foreground">
          ⌘K
        </kbd>
      </button>

      {/* Simulated Feed Pill */}
      {isMock && (
        <span className="hidden rounded-sm border border-warn/40 bg-warn/10 px-1.5 py-0.5 text-[10px] normal-case tracking-normal text-warn lg:inline">
          SIMULATED FEED
        </span>
      )}

      {/* Real-time Clock */}
      <span className="tnum whitespace-nowrap text-muted-foreground">{clock}</span>
    </header>
  )
}