"use client"

import { useHealth } from "@/lib/hooks"
import { AlertTriangle, CheckCircle2, Cpu, Database, Loader2, TerminalSquare } from "lucide-react"

export function QueryConsole() {
  const { data: health, isLoading, error } = useHealth()

  const dbConnected = health?.db_connected ?? false
  const modelReady = health?.model_loaded ?? false
  const isMock = health?.source === "mock" || !health

  return (
    <footer className="flex h-8 items-center gap-3 overflow-hidden border-t border-border-strong bg-surface px-3 font-mono text-[10px]">
      {/* Console Title */}
      <div className="flex shrink-0 items-center gap-1.5">
        <TerminalSquare className="h-3.5 w-3.5 text-accent" />
        <span className="font-semibold uppercase tracking-widest text-foreground">
          Telemetry & OLAP Engine
        </span>
        <span className="text-border-strong">|</span>
      </div>

      {/* Engine Status Indicators */}
      <div className="hidden shrink-0 items-center gap-4 sm:flex">
        {/* DuckDB Status */}
        <div className="flex items-center gap-1.5">
          <span className={`h-2 w-2 rounded-full ${dbConnected ? 'led-up' : 'led-down'}`} />
          <Database className="h-3 w-3 text-dim" />
          <span className="text-dim">DuckDB:</span>
          <span className={`tnum font-semibold ${dbConnected ? "text-up" : "text-down"}`}>
            {dbConnected ? "READ_ONLY ASOF" : "OFFLINE"}
          </span>
        </div>

        {/* XGBoost Status */}
        <div className="flex items-center gap-1.5">
          <span className={`h-2 w-2 rounded-full ${modelReady ? 'led-up' : 'led-warn'}`} />
          <Cpu className="h-3 w-3 text-dim" />
          <span className="text-dim">XGBoost:</span>
          <span className={`tnum font-semibold ${modelReady ? "text-up" : "text-warn"}`}>
            {modelReady ? "ONLINE (τ=0.89)" : "UNLOADED"}
          </span>
        </div>
      </div>

      <span className="hidden shrink-0 text-border-strong sm:inline">|</span>

      {/* Contextual Diagnosis Stream */}
      <div className="min-w-0 flex-1 truncate">
        {isLoading ? (
          <span className="flex items-center gap-1.5 text-dim">
            <Loader2 className="h-2.5 w-2.5 animate-spin text-accent" />
            Polling engine diagnostics...
          </span>
        ) : error ? (
          <span className="text-down">
            Backend offline — Run `python src/api/main.py` on :8000 to bind live analytics stream
          </span>
        ) : isMock ? (
          <span className="text-warn">
            Operating in fallback sandbox — Serving deterministic catalog fixtures with zero drift
          </span>
        ) : (
          <span className="text-foreground/90">
            Columnar DuckDB mounted · Temporal ASOF alignment active · Pure chronological 14D embargo verified
          </span>
        )}
      </div>

      {/* Hardware-Style Environment Pill */}
      <div className="flex shrink-0 items-center gap-2">
        {isMock ? (
          <span className="inline-flex items-center gap-1.5 rounded-[2px] border border-warn/40 bg-warn/10 px-2 py-0.5 text-[9px] font-semibold tracking-wider text-warn">
            <span className="h-1.5 w-1.5 rounded-full led-warn" />
            MOCK SANDBOX
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 rounded-[2px] border border-up/40 bg-up/10 px-2 py-0.5 text-[9px] font-semibold tracking-wider text-up">
            <span className="h-1.5 w-1.5 rounded-full led-up" />
            LIVE PIPELINE
          </span>
        )}
        <span className="text-accent animate-blink" aria-hidden>
          ▊
        </span>
      </div>
    </footer>
  )
}