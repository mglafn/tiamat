"use client"

import { useSummary, useForecast, usePrintings } from "@/lib/hooks"
import { usd, pct, shortUuid } from "@/lib/format"

interface TelemetryPanelProps {
  uuid: string | null
  selectedFinish?: string
  onSelectUuid?: (uuid: string) => void
}

function Row({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between border-b border-border/50 py-1 text-[11px]">
      <span className="uppercase text-dim">{label}</span>
      <span className={`tnum ${tone ?? "text-foreground"}`}>{value}</span>
    </div>
  )
}

export function TelemetryPanel({ uuid, selectedFinish = "normal", onSelectUuid }: TelemetryPanelProps) {
  const { data: summary } = useSummary(uuid)
  const { data: forecast } = useForecast(uuid, "tcgplayer", selectedFinish)
  const { printings } = usePrintings(uuid)
  
  // Hydrate directly from summary payload
  const name = summary?.name ?? (uuid ? shortUuid(uuid) : null)
  const setCode = summary?.set_code ?? "—"

  // Distribution bar: floor -> avg -> ceiling positioning.
  const dist = summary
    ? {
        floorPos: 0,
        avgPos: ((summary.avg_price - summary.floor_price) / Math.max(summary.ceiling_price - summary.floor_price, 0.01)) * 100,
        ceilPos: 100,
      }
    : null

  return (
    <section className="flex min-h-0 flex-col border-l border-border-strong bg-panel" aria-label="Execution telemetry">
      <div className="border-b border-border-strong bg-surface px-3 py-1.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-foreground">Execution Telemetry</h2>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {!uuid && <p className="text-[11px] text-dim">No SKU selected.</p>}

        {uuid && (
          <>
            {/* Selected SKU card */}
            <div className="rounded-sm border border-border-strong bg-surface p-2.5">
              <div className="text-[10px] uppercase text-dim">Selected SKU</div>
              <div className="mt-0.5 text-[13px] text-accent text-pretty">{name}</div>
              <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                <div className="flex justify-between">
                  <span className="text-dim">Finish</span>
                  <span className="capitalize text-foreground">{selectedFinish}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-dim">Active Set</span>
                  <span className="text-foreground font-semibold">{setCode}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-dim">Vendor</span>
                  <span className="truncate text-foreground">{summary?.primary_vendor ?? "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-dim">Variants</span>
                  <span className="tnum text-foreground">{summary?.total_market_variants ?? "—"}</span>
                </div>
              </div>

              {/* Set Printing Toggle Badges */}
              {printings.length > 1 && (
                <div className="mt-2.5 pt-2 border-t border-border/60">
                  <div className="mb-1.5 text-[10px] uppercase text-dim">Available Printings</div>
                  <div className="flex flex-wrap gap-1">
                    {printings.map((p) => {
                      const isActive = p.uuid === uuid
                      return (
                        <button
                          key={p.uuid}
                          type="button"
                          onClick={() => onSelectUuid?.(p.uuid)}
                          className={`rounded px-1.5 py-0.5 text-[10px] font-mono uppercase transition-colors ${
                            isActive
                              ? "bg-accent text-accent-foreground font-bold"
                              : "border border-border bg-surface-2 text-dim hover:border-accent hover:text-foreground"
                          }`}
                        >
                          {p.set_code}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>

            {/* Price distribution */}
            {summary && dist && (
              <div className="mt-3">
                <div className="mb-1.5 text-[10px] uppercase text-dim">Vendor Price Distribution</div>
                <div className="relative h-1.5 rounded-full bg-surface-2">
                  <div
                    className="absolute inset-y-0 rounded-full bg-accent/40"
                    style={{ left: 0, right: `${100 - dist.avgPos}%` }}
                  />
                  <div className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 bg-accent" style={{ left: `calc(${dist.avgPos}% - 1px)` }} />
                </div>
                <div className="mt-2">
                  <Row label="Vendor Floor" value={usd(summary.floor_price)} tone="text-down" />
                  <Row label="Market Mean" value={usd(summary.avg_price)} />
                  <Row label="Vendor Peak" value={usd(summary.ceiling_price)} tone="text-up" />
                  <Row
                    label="Spread"
                    value={`${usd(summary.ceiling_price - summary.floor_price)} · ${pct(((summary.ceiling_price - summary.floor_price) / summary.floor_price) * 100, false)}`}
                    tone="text-warn"
                  />
                </div>
              </div>
            )}

            {/* Model inference */}
            {forecast && (
              <div className="mt-3">
                <div className="mb-1.5 text-[10px] uppercase text-dim">XGBoost Inference</div>
                <Row label="Current" value={usd(forecast.current_price)} />
                <Row label="Predicted 7D" value={usd(forecast.predicted_7d_price)} tone="text-forecast" />
                <Row
                  label="Expected Gain"
                  value={pct(forecast.predicted_gain_pct)}
                  tone={forecast.predicted_gain_pct >= 0 ? "text-up" : "text-down"}
                />
                <Row label="Model MAE" value={usd(forecast.model_mae)} tone="text-muted-foreground" />
              </div>
            )}

            {/* Confidence gauge */}
            {forecast && (
              <div className="mt-3 rounded-sm border border-border bg-surface/50 p-2.5">
                <div className="flex items-center justify-between text-[10px] uppercase">
                  <span className="text-dim">Signal</span>
                  <span className={forecast.predicted_gain_pct >= 0 ? "text-up" : "text-down"}>
                    {forecast.predicted_gain_pct >= 5 ? "STRONG BUY" : forecast.predicted_gain_pct >= 0 ? "ACCUMULATE" : "REDUCE"}
                  </span>
                </div>
                <p className="mt-1 text-[10px] leading-relaxed text-dim">
                  {"7-day forward projection derived from SMA-7/SMA-30 momentum and daily-return features."}
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}