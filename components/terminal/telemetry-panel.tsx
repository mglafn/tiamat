"use client"

import { useSummary, useForecast, usePrintings } from "@/lib/hooks"
import { usd, pct, shortUuid } from "@/lib/format"
import type { CardVariant } from "@/lib/types"

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
  const collectorNum = summary?.collector_number ? `#${summary.collector_number}` : ""
  const edhrecRank = summary?.edhrec_rank

  // Distribution bar: floor -> avg -> ceiling positioning
  const hasValidPriceRange =
    summary != null &&
    summary.floor_price != null &&
    summary.ceiling_price != null &&
    summary.ceiling_price > 0

  const dist =
    hasValidPriceRange && summary
      ? {
          floorPos: 0,
          avgPos: Math.min(
            100,
            Math.max(
              0,
              ((summary.avg_price - summary.floor_price) /
                Math.max(summary.ceiling_price - summary.floor_price, 0.01)) *
                100
            )
          ),
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
              <div className="flex items-center justify-between text-[10px] uppercase text-dim">
                <span>Selected SKU</span>
                {collectorNum && <span className="font-mono text-dim">{collectorNum}</span>}
              </div>
              <div className="mt-0.5 text-pretty text-[13px] font-medium text-accent">{name}</div>
              <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                <div className="flex justify-between">
                  <span className="text-dim">Finish</span>
                  <span className="capitalize text-foreground">{selectedFinish}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-dim">Active Set</span>
                  <span className="font-semibold text-foreground">{setCode}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-dim">Vendor</span>
                  <span className="truncate text-foreground">{summary?.primary_vendor ?? "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-dim">Variants</span>
                  <span className="tnum text-foreground">{summary?.total_market_variants ?? "—"}</span>
                </div>
                {edhrecRank != null && (
                  <div className="col-span-2 mt-1 flex items-center justify-between border-t border-border/40 pt-1 text-[10px]">
                    <span className="uppercase text-dim">Demand Rank</span>
                    <span className="font-mono font-semibold text-up">#{edhrecRank.toLocaleString()} (EDHREC)</span>
                  </div>
                )}
              </div>
            </div>

            {/* Scryfall-Style Available Printings & Multi-Variant Table */}
            {printings.length > 0 && (
              <div className="mt-3">
                <div className="mb-1.5 flex items-center justify-between text-[10px] uppercase text-dim">
                  <span>Available Printings</span>
                  <span className="tnum">{printings.length} variants</span>
                </div>
                <div className="max-h-40 overflow-y-auto divide-y divide-border/40 rounded-sm border border-border bg-surface/60">
                  {printings.map((p: CardVariant, i: number) => {
                    const isActive = p.uuid === uuid
                    const hasPrice = p.floor_price != null

                    return (
                      <button
                        key={`${p.uuid}-${p.set_code}-${i}`}
                        type="button"
                        onClick={() => onSelectUuid?.(p.uuid)}
                        className={`flex w-full items-center justify-between px-2.5 py-1.5 text-left text-[11px] transition-colors ${
                          isActive
                            ? "border-l-2 border-accent bg-accent/20 font-semibold text-accent"
                            : "text-foreground hover:bg-surface-2"
                        }`}
                      >
                        <div className="flex items-center gap-2 truncate">
                          <span className="font-mono text-[10px] text-dim">
                            {p.collector_number ? `#${p.collector_number}` : "—"}
                          </span>
                          <span className="font-semibold">{p.set_code}</span>
                          {p.edhrec_rank != null && (
                            <span className="hidden font-mono text-[9px] text-muted-foreground sm:inline">
                              (r:{p.edhrec_rank})
                            </span>
                          )}
                        </div>

                        {/* Distinct styling for active price vs true $0.00 vs NO DATA */}
                        {hasPrice ? (
                          <span
                            className={`tnum font-mono text-[11px] ${
                              p.floor_price === 0 ? "text-muted-foreground" : "font-medium text-foreground"
                            }`}
                          >
                            {usd(p.floor_price)}
                          </span>
                        ) : (
                          <span className="font-mono text-[10px] uppercase tracking-wider text-dim/60">
                            NO DATA
                          </span>
                        )}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Price distribution */}
            {summary && dist && (
              <div className="mt-3">
                <div className="mb-1.5 text-[10px] uppercase text-dim">Vendor Price Distribution</div>
                <div className="relative h-1.5 rounded-full bg-surface-2">
                  <div
                    className="absolute inset-y-0 rounded-full bg-accent/40"
                    style={{ left: 0, right: `${100 - dist.avgPos}%` }}
                  />
                  <div
                    className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 bg-accent"
                    style={{ left: `calc(${dist.avgPos}% - 1px)` }}
                  />
                </div>
                <div className="mt-2">
                  <Row label="Vendor Floor" value={usd(summary.floor_price)} tone="text-down" />
                  <Row label="Market Mean" value={usd(summary.avg_price)} />
                  <Row label="Vendor Peak" value={usd(summary.ceiling_price)} tone="text-up" />
                  <Row
                    label="Spread"
                    value={
                      summary.floor_price != null && summary.floor_price > 0 && summary.ceiling_price != null
                        ? `${usd(summary.ceiling_price - summary.floor_price)} · ${pct(
                            ((summary.ceiling_price - summary.floor_price) / summary.floor_price) * 100,
                            false
                          )}`
                        : "—"
                    }
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
                    {forecast.predicted_gain_pct >= 5
                      ? "STRONG BUY"
                      : forecast.predicted_gain_pct >= 0
                        ? "ACCUMULATE"
                        : "REDUCE"}
                  </span>
                </div>
                <p className="mt-1 text-[10px] leading-relaxed text-dim">
                  7-day forward projection derived from SMA-7/SMA-30 momentum and daily-return features.
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}