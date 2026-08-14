"use client"

import { useEffect, useState } from "react"

const LOG_LINES = [
  "DUCKDB> SELECT * FROM fact_arbitrage_opportunities ORDER BY price_spread DESC LIMIT 60;",
  "  → 60 rows · window latency 1.28ms · columnar scan hit",
  "XGB> predict(current_price, sma_7, sma_30, daily_return_pct)",
  "  → inference 0.4ms · training cache ACTIVE",
  "DUCKDB> AVG(current_price) OVER (PARTITION BY uuid ORDER BY price_date ROWS 6 PRECEDING)",
  "  → SMA-7 materialized · 24 partitions",
]

export function QueryConsole() {
  const [latency, setLatency] = useState(1.28)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const id = setInterval(() => {
      setLatency(Number((1.0 + Math.random() * 0.9).toFixed(2)))
      setTick((t) => t + 1)
    }, 2600)
    return () => clearInterval(id)
  }, [])

  const line = LOG_LINES[tick % LOG_LINES.length]

  return (
    <footer className="flex h-9 items-center gap-3 overflow-hidden border-t border-border-strong bg-surface px-3 text-[10px]">
      <span className="shrink-0 font-semibold uppercase tracking-widest text-accent">Query Console</span>
      <span className="tnum shrink-0 text-dim">
        Windowing {latency}ms · Training Cache <span className="text-up">ACTIVE</span>
      </span>
      <span className="min-w-0 flex-1 truncate text-muted-foreground">{line}</span>
      <span className="shrink-0 text-accent animate-blink" aria-hidden>
        ▊
      </span>
    </footer>
  )
}
