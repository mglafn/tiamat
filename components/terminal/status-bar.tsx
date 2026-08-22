'use client'

import { useEffect, useState } from 'react'
import { Search } from 'lucide-react'
import { useHealth } from '@/lib/hooks'

interface StatusBarProps {
  onOpenSearch: () => void
  mode?: 'NORMAL' | 'BATCH' | 'SEARCH'
}

export function StatusBar({
  onOpenSearch,
  mode = 'NORMAL',
}: StatusBarProps) {
  const [clock, setClock] = useState('--:--:--')
  const { data: health } = useHealth()
  const dbConnected = health?.db_connected ?? true
  const modelReady = health?.model_loaded ?? true
  const isHealthy = health?.status === 'healthy' || !health

  useEffect(() => {
    const tick = () => {
      const d = new Date()
      setClock(d.toLocaleTimeString('en-US', { hour12: false }))
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <header className="flex h-8 shrink-0 items-center gap-3 border-b border-border-strong bg-surface px-3 text-[10px] uppercase tracking-wide">
      <div className="flex items-center gap-1.5">
        <span
          className={`rounded-[1px] px-1.5 py-0.5 font-bold tracking-wider ${
            mode === 'BATCH'
              ? 'bg-warn text-warn-foreground'
              : mode === 'SEARCH'
                ? 'bg-accent text-accent-foreground'
                : 'bg-surface-2 text-foreground'
          }`}
        >
          {mode}
        </span>
        <span
          className={`h-1.5 w-1.5 rounded-full ${isHealthy ? 'bg-up animate-blink' : 'bg-warn'}`}
          aria-hidden
        />
      </div>

      <Stat
        label="DuckDB"
        value={dbConnected ? 'Mounted' : 'Offline'}
        tone={dbConnected ? 'text-up' : 'text-down'}
      />
      <Stat
        label="XGBoost"
        value={modelReady ? 'Online' : 'Unloaded'}
        tone={modelReady ? 'text-up' : 'text-warn'}
      />
      <span className="hidden text-dim sm:inline">
        Feed <span className="text-accent">Persistent IPC</span>
      </span>

      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          onClick={onOpenSearch}
          className="flex items-center gap-2 rounded-sm border border-border bg-surface-2 px-2 py-0.5 text-dim transition-colors hover:border-border-strong hover:text-foreground"
        >
          <Search className="h-3 w-3" />
          <span>Search Card</span>
          <kbd className="rounded-sm border border-border-strong bg-background px-1 text-[9px] text-muted-foreground">
            ⌘K
          </kbd>
        </button>

        <span className="tnum hidden text-muted-foreground md:inline">{clock}</span>
      </div>
    </header>
  )
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone: string
}) {
  return (
    <span className="hidden items-center gap-1 md:flex">
      <span className="text-dim">{label}:</span>
      <span className={tone}>{value}</span>
    </span>
  )
}