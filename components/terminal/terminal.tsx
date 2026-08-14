"use client"
import { useCallback, useEffect, useState } from "react"
import { StatusBar } from "./status-bar"
import { Ticker } from "./ticker"
import { ArbitrageBook } from "./arbitrage-book"
import { ForecastPanel } from "./forecast-panel"
import { TelemetryPanel } from "./telemetry-panel"
import { QueryConsole } from "./query-console"
import { CommandPalette } from "./command-palette"

export function Terminal() {
  const [selectedUuid, setSelectedUuid] = useState<string | null>(null)
  const [selectedFinish, setSelectedFinish] = useState<string>("normal")
  const [minSpread, setMinSpread] = useState(0) // Default to 0 so the whole catalogue is instantly visible
  const [finish, setFinish] = useState("all")
  const [paletteOpen, setPaletteOpen] = useState(false)
  
  // Global ⌘K / Ctrl+K to open search
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setPaletteOpen((o) => !o)
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [])

  const handleSelect = useCallback((uuid: string, rowFinish: string = "normal") => {
    setSelectedUuid(uuid)
    setSelectedFinish(rowFinish)
  }, [])

  return (
    <div className="grid-scan flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      <StatusBar onOpenSearch={() => setPaletteOpen(true)} />
      <Ticker />
      <main className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[340px_minmax(0,1fr)_300px] xl:grid-cols-[380px_minmax(0,1fr)_320px]">
        <div className="h-full min-h-0 overflow-hidden max-lg:h-[42vh] max-lg:border-b max-lg:border-border-strong">
          <ArbitrageBook
            minSpread={minSpread}
            setMinSpread={setMinSpread}
            finish={finish}
            setFinish={setFinish}
            selectedUuid={selectedUuid}
            selectedFinish={selectedFinish}
            onSelect={handleSelect}
          />
        </div>
        <div className="h-full min-h-0 overflow-hidden max-lg:h-[52vh]">
          <ForecastPanel 
            uuid={selectedUuid} 
            selectedFinish={selectedFinish}
            onFinishChange={setSelectedFinish}
          />
        </div>
        <div className="h-full min-h-0 overflow-hidden max-lg:border-t max-lg:border-border-strong">
          <TelemetryPanel 
            uuid={selectedUuid} 
            selectedFinish={selectedFinish}
          />
        </div>
      </main>
      <QueryConsole />
      <CommandPalette 
        open={paletteOpen} 
        onClose={() => setPaletteOpen(false)} 
        onSelect={handleSelect} 
      />
    </div>
  )
}