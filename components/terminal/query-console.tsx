"use client"

import { useHealth } from "@/lib/hooks"
import { AlertTriangle, CheckCircle2, Cpu, Database, Loader2 } from "lucide-react"

export function QueryConsole() {
  const { data: health, isLoading, error } = useHealth()

  const dbConnected = health?.db_connected ?? false
  const modelReady = health?.model_loaded ?? false
  const isMock = health?.source === "mock" || !health

  return (
    <footer className="flex h-9 items-center gap-3 overflow-hidden border-t border-border-strong bg-surface px-3 text-[10px]">
      {/* Console Label */}
      <div className="flex shrink-0 items-center gap-1.5">
        <span className="font-semibold uppercase tracking-widest text-accent">
          Query Console
        </span>
        <span className="text-border-strong">|</span>
      </div>

      {/* Real Engine Diagnostics */}
      <div className="hidden shrink-0 items-center gap-3 sm:flex">
        {/* DuckDB Status */}
        <div className="flex items-center gap-1.5">
          <Database className="h-3 w-3 text-dim" />
          <span className="text-dim">DuckDB:</span>
          <span className={`tnum font-medium ${dbConnected ? "text-up" : "text-down"}`}>
            {dbConnected ? "READ_ONLY" : "OFFLINE"}
          </span>
        </div>

        {/* XGBoost Status */}
        <div className="flex items-center gap-1.5">
          <Cpu className="h-3 w-3 text-dim" />
          <span className="text-dim">XGBoost:</span>
          <span className={`tnum font-medium ${modelReady ? "text-up" : "text-warn"}`}>
            {modelReady ? "ONLINE" : "UNLOADED"}
          </span>
        </div>
      </div>

      <span className="hidden shrink-0 text-border-strong sm:inline">|</span>

      {/* Contextual Status Message */}
      <div className="min-w-0 flex-1 truncate">
        {isLoading ? (
          <span className="flex items-center gap-1.5 text-dim">
            <Loader2 className="h-2.5 w-2.5 animate-spin text-accent" />
            Polling engine diagnostics...
          </span>
        ) : error ? (
          <span className="text-down">
            Backend offline — Run `python src/api/main.py` on :8000 to enable live analytics
          </span>
        ) : isMock ? (
          <span className="text-warn">
            Operating in fallback sandbox — Serving deterministic catalog fixtures
          </span>
        ) : (
          <span className="text-foreground/80">
            Columnar store mounted · Temporal ASOF alignment active · 7D forecast ready
          </span>
        )}
      </div>

      {/* Live/Mock Environment Indicator */}
      <div className="flex shrink-0 items-center gap-2">
        {isMock ? (
          <span className="inline-flex items-center gap-1 rounded-sm border border-warn/40 bg-warn/10 px-1.5 py-0.5 text-[9px] font-medium tracking-wide text-warn">
            <AlertTriangle className="h-2.5 w-2.5" />
            MOCK FEED
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-sm border border-up/40 bg-up/10 px-1.5 py-0.5 text-[9px] font-medium tracking-wide text-up">
            <CheckCircle2 className="h-2.5 w-2.5" />
            LIVE BACKEND
          </span>
        )}
        <span className="text-accent animate-blink" aria-hidden>
          ▊
        </span>
      </div>
    </footer>
  )
}