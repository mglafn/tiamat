'use client'

import { useCallback, useEffect, useState } from 'react'
import { StatusBar } from './status-bar'
import { Ticker } from './ticker'
import { ArbitrageBook } from './arbitrage-book'
import { ForecastPanel } from './forecast-panel'
import { TelemetryPanel } from './telemetry-panel'
import { QueryConsole } from './query-console'
import { CommandPalette } from './command-palette'
import { MethodologyModal } from './methodology-modal'
import { StrategyLabModal } from './strategy-lab-modal'

export function Terminal() {
  const [selectedUuid, setSelectedUuid] = useState<string | null>(null)
  const [selectedFinish, setSelectedFinish] = useState<string>('normal')
  const [minSpread, setMinSpread] = useState(0)
  const [finish, setFinish] = useState('all')
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [docsOpen, setDocsOpen] = useState(false)
  const [strategyOpen, setStrategyOpen] = useState(false)
  const [stagedUuids, setStagedUuids] = useState<Set<string>>(new Set())

  const currentMode = strategyOpen
    ? 'STRATEGY'
    : docsOpen
      ? 'DOCS'
      : paletteOpen
        ? 'SEARCH'
        : stagedUuids.size > 0
          ? 'BATCH'
          : 'NORMAL'

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((o) => !o)
      } else if (e.key.toLowerCase() === 'b' && !e.metaKey && !e.ctrlKey) {
        e.preventDefault()
        setStrategyOpen((o) => !o)
      } else if (e.key === '?' || ((e.metaKey || e.ctrlKey) && e.key === '/')) {
        e.preventDefault()
        setDocsOpen((d) => !d)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const handleSelect = useCallback((uuid: string, rowFinish: string = 'normal') => {
    setSelectedUuid(uuid)
    setSelectedFinish(rowFinish)
  }, [])

  const handleToggleStage = useCallback((uuid: string) => {
    setStagedUuids((prev) => {
      const next = new Set(prev)
      if (next.has(uuid)) {
        next.delete(uuid)
      } else {
        next.add(uuid)
      }
      return next
    })
  }, [])

  return (
    <div className="grid-scan flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      {/* Top Application Status Bar */}
      <StatusBar
        onOpenSearch={() => setPaletteOpen(true)}
        onOpenDocs={() => setDocsOpen(true)}
        onOpenStrategy={() => setStrategyOpen(true)}
        mode={currentMode as 'NORMAL' | 'BATCH' | 'SEARCH' | 'DOCS' | 'STRATEGY'}
      />

      {/* Real-time Cross-Market Spread Ticker */}
      <Ticker />

      {/* 3-Column Quant Terminal Layout */}
      <main className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[340px_minmax(0,1fr)_300px] xl:grid-cols-[380px_minmax(0,1fr)_340px]">
        {/* Column 1: Cross-Vendor Arbitrage Book */}
        <div className="h-full min-h-0 overflow-hidden max-lg:h-[42vh] max-lg:border-b max-lg:border-border-strong">
          <ArbitrageBook
            minSpread={minSpread}
            setMinSpread={setMinSpread}
            finish={finish}
            setFinish={setFinish}
            selectedUuid={selectedUuid}
            selectedFinish={selectedFinish}
            onSelect={handleSelect}
            stagedUuids={stagedUuids}
            onToggleStage={handleToggleStage}
          />
        </div>

        {/* Column 2: Time-Series & 7D XGBoost Forecast Panel */}
        <div className="h-full min-h-0 overflow-hidden max-lg:h-[52vh]">
          <ForecastPanel
            uuid={selectedUuid}
            selectedFinish={selectedFinish}
            onFinishChange={setSelectedFinish}
            onSelectUuid={(newUuid) => handleSelect(newUuid, selectedFinish)}
          />
        </div>

        {/* Column 3: Unit Economics & Telemetry */}
        <div className="h-full min-h-0 overflow-hidden max-lg:border-t max-lg:border-border-strong">
          <TelemetryPanel
            uuid={selectedUuid}
            selectedFinish={selectedFinish}
            onSelectUuid={(newUuid) => handleSelect(newUuid, selectedFinish)}
          />
        </div>
      </main>

      {/* Bottom Engine Telemetry Console */}
      <QueryConsole />

      {/* Command Palette Modal */}
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onSelect={handleSelect}
        onOpenDocs={() => setDocsOpen(true)}
      />

      {/* Methodology Documentation Modal */}
      <MethodologyModal
        open={docsOpen}
        onClose={() => setDocsOpen(false)}
      />

      {/* Quantitative Strategy Backtest Lab */}
      <StrategyLabModal
        open={strategyOpen}
        onClose={() => setStrategyOpen(false)}
      />
    </div>
  )
}