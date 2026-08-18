"use client"

import { useMemo } from "react"
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

function calculateDirectPayout(price: number, taxRate = 0.075, clampDeadZone = true): number {
  if (price < 0.40) return 0.0

  const p = clampDeadZone && price >= 2.50 && price <= 2.67 ? 2.49 : price

  if (p < 2.50) {
    return Number((p * 0.50).toFixed(2))
  }

  const commission = Math.min(p * 0.0895, 75.00)
  const processing = p * (1.0 + taxRate) * 0.025
  const totalFee = 1.12 + commission + processing
  return Math.max(0, Number((p - totalFee).toFixed(2)))
}

function calculateConditionRiskHaircut(
  directPrice: number,
  acqCost: number,
  downgradeRate = 0.035,
  rejectRate = 0.005,
  salvageFactor = 0.75
): number {
  const safeDirect = Math.max(0.40, directPrice)
  const downgradePenalty = (safeDirect - (salvageFactor * acqCost)) / safeDirect
  const penalty = (downgradeRate * Math.max(0, downgradePenalty)) + (rejectRate * 1.0)
  return Math.max(0.80, Math.min(1.00, 1.0 - penalty))
}

export function TelemetryPanel({ uuid, selectedFinish = "normal", onSelectUuid }: TelemetryPanelProps) {
  const { data: summary } = useSummary(uuid)
  const { data: forecast } = useForecast(uuid, "tcgplayer", selectedFinish)
  const { printings } = usePrintings(uuid)

  const name = summary?.name ?? (uuid ? shortUuid(uuid) : null)
  const setCode = summary?.set_code ?? "—"
  const collectorNum = summary?.collector_number ? `#${summary.collector_number}` : ""
  const edhrecRank = summary?.edhrec_rank

  const hasValidPriceRange =
    summary != null &&
    summary.floor_price != null &&
    summary.ceiling_price != null &&
    summary.avg_price != null &&
    summary.ceiling_price > 0 &&
    summary.ceiling_price >= summary.floor_price

  const spreadDiff = hasValidPriceRange && summary?.ceiling_price != null && summary?.floor_price != null
    ? summary.ceiling_price - summary.floor_price
    : 0

  const dist =
    hasValidPriceRange && summary && summary.floor_price != null && summary.avg_price != null
      ? {
          floorPos: 0,
          avgPos: Math.min(
            100,
            Math.max(
              0,
              ((summary.avg_price - summary.floor_price) / Math.max(spreadDiff, 0.01)) * 100
            )
          ),
          ceilPos: 100,
        }
      : null

  // Execution signals calibrated against TCGplayer Direct rate rules
  const currentPrice = forecast?.current_price ?? 0
  const grossGainPct = forecast?.predicted_gain_pct ?? 0
  const dirAcc = forecast?.directional_accuracy_pct ?? 50.0

  const {
    acquisitionCost,
    expectedExitPayout,
    netExpectedRoi,
    isDeadZoneClamped,
    kappaRisk,
    signalLabel,
    signalTone,
    signalDescription
  } = useMemo(() => {
    if (!forecast || currentPrice <= 0) {
      return {
        acquisitionCost: null,
        expectedExitPayout: null,
        netExpectedRoi: null,
        isDeadZoneClamped: false,
        kappaRisk: null,
        signalLabel: "NEUTRAL / NO DATA",
        signalTone: "text-muted-foreground font-semibold",
        signalDescription: "Model confidence is baseline. Select a tracked asset to inspect execution signals.",
      }
    }

    // Landed cost basis: gross price + tax + inbound postage + freight
    const inboundPostage = currentPrice < 5.00 ? 0.99 : 0.15
    const hubFreight = 0.012
    const totalAcquisition = (currentPrice * 1.075) + inboundPostage + hubFreight

    // Net Direct payout with condition downgrade risk haircut (kappa_risk)
    const targetPrice = forecast.predicted_7d_price
    const isClamped = targetPrice >= 2.50 && targetPrice <= 2.67
    const rawPayout = calculateDirectPayout(targetPrice, 0.075, true)
    
    const kappa = forecast.kappa_risk ?? calculateConditionRiskHaircut(targetPrice, totalAcquisition)
    const netPayout = forecast.expected_net_payout ?? (rawPayout * kappa)
    const netRoi = forecast.net_expected_roi_pct ?? (((netPayout - totalAcquisition) / totalAcquisition) * 100.0)

    if (netRoi >= 10.0 && dirAcc >= 60.0) {
      return {
        acquisitionCost: totalAcquisition,
        expectedExitPayout: netPayout,
        netExpectedRoi: netRoi,
        isDeadZoneClamped: isClamped,
        kappaRisk: kappa,
        signalLabel: "STRONG ACCUMULATE",
        signalTone: "text-up font-semibold",
        signalDescription: `Breakout catalyst confirmed (Model Accuracy: ${dirAcc.toFixed(1)}%). Risk-adjusted Net ROI (${netRoi > 0 ? "+" : ""}${netRoi.toFixed(1)}%) clears the 10.0% hurdle after all Direct fees, condition haircuts, taxes, and freight.`,
      }
    }

    if (netRoi >= 0.0 && grossGainPct >= 4.5) {
      return {
        acquisitionCost: totalAcquisition,
        expectedExitPayout: netPayout,
        netExpectedRoi: netRoi,
        isDeadZoneClamped: isClamped,
        kappaRisk: kappa,
        signalLabel: "ACCUMULATE",
        signalTone: "text-up font-semibold",
        signalDescription: `Projected price gain (+${grossGainPct.toFixed(1)}%) clears the landed friction baseline. Risk-adjusted net margin is positive (+${netRoi.toFixed(1)}%).`,
      }
    }

    if (grossGainPct <= -15.0) {
      return {
        acquisitionCost: totalAcquisition,
        expectedExitPayout: netPayout,
        netExpectedRoi: netRoi,
        isDeadZoneClamped: isClamped,
        kappaRisk: kappa,
        signalLabel: "STRONG REDUCE",
        signalTone: "text-down font-semibold",
        signalDescription: "Severe downward momentum detected. High probability of buybox collapse or liquidity exhaustion over the 7-day horizon.",
      }
    }

    if (grossGainPct <= -5.0) {
      return {
        acquisitionCost: totalAcquisition,
        expectedExitPayout: netPayout,
        netExpectedRoi: netRoi,
        isDeadZoneClamped: isClamped,
        kappaRisk: kappa,
        signalLabel: "REDUCE EXPOSURE",
        signalTone: "text-down font-semibold",
        signalDescription: "Negative momentum trajectory detected. Consider offloading exposure into buylists.",
      }
    }

    return {
      acquisitionCost: totalAcquisition,
      expectedExitPayout: netPayout,
      netExpectedRoi: netRoi,
      isDeadZoneClamped: isClamped,
      kappaRisk: kappa,
      signalLabel: "NEUTRAL HOLD",
      signalTone: "text-dim font-semibold",
      signalDescription: grossGainPct > 0 
        ? `Projected gross gain (+${grossGainPct.toFixed(1)}%) is insufficient to overcome Direct fulfillment friction, condition risk, and landed costs. Net ROI is negative (${netRoi.toFixed(1)}%).`
        : "Asset is in a low-volatility resting state. Model confidence threshold not triggered.",
    }
  }, [forecast, currentPrice, grossGainPct, dirAcc])

  return (
    <section className="flex min-h-0 flex-col border-l border-border-strong bg-panel" aria-label="Execution telemetry">
      <div className="border-b border-border-strong bg-surface px-3 py-1.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-foreground">Execution Telemetry</h2>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {!uuid && <p className="text-[11px] text-dim">No asset selected.</p>}

        {uuid && (
          <>
            {/* Metadata */}
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

            {/* Set printings */}
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
                        </div>

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

            {/* Vendor price spread */}
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

            {/* Direct fulfillment telemetry */}
            {forecast && (
              <div className="mt-3">
                <div className="mb-1.5 text-[10px] uppercase text-dim">Direct / SYP Execution Telemetry</div>
                <Row label="Current Close" value={usd(forecast.current_price)} />
                {acquisitionCost != null && (
                  <Row label="Landed Cost Basis" value={usd(acquisitionCost)} tone="text-muted-foreground" />
                )}
                <Row label="Projected 7D Target" value={usd(forecast.predicted_7d_price)} tone="text-forecast font-medium" />
                {expectedExitPayout != null && (
                  <Row label="Risk-Adj. Net Payout" value={usd(expectedExitPayout)} tone="text-foreground font-medium" />
                )}
                <Row
                  label="Gross Return"
                  value={pct(forecast.predicted_gain_pct)}
                  tone={forecast.predicted_gain_pct >= 0 ? "text-up font-medium" : "text-down font-medium"}
                />
                {netExpectedRoi != null && (
                  <Row
                    label="Net Expected ROI"
                    value={pct(netExpectedRoi)}
                    tone={netExpectedRoi >= 10.0 ? "text-up font-bold" : netExpectedRoi >= 0 ? "text-up font-medium" : "text-down"}
                  />
                )}
                {kappaRisk != null && (
                  <Row label="Condition Haircut (κ)" value={`${(kappaRisk * 100).toFixed(1)}%`} tone="text-dim" />
                )}
                <Row label="Error Bound (MAE)" value={`±${usd(forecast.model_mae)}`} tone="text-muted-foreground" />
                {forecast.directional_accuracy_pct != null && (
                  <Row 
                    label="Model Directional Accuracy" 
                    value={`${forecast.directional_accuracy_pct}%`} 
                    tone={forecast.directional_accuracy_pct >= 60 ? "text-up font-medium" : "text-dim"} 
                  />
                )}
              </div>
            )}

            {/* Dead zone notice */}
            {isDeadZoneClamped && (
              <div className="mt-2 rounded-sm border border-warn/40 bg-warn/10 p-2 text-[10px] text-warn">
                ⚡ <strong>Fee-Cliff Clamped:</strong> Target price was in the [$2.50, $2.67] dead zone. Exit pegged to $2.49 to optimize net margin.
              </div>
            )}

            {/* Action signal */}
            {forecast && (
              <div className="mt-3 rounded-sm border border-border bg-surface/50 p-2.5">
                <div className="flex items-center justify-between text-[10px] uppercase">
                  <span className="text-dim">Execution Signal</span>
                  <span className={signalTone}>{signalLabel}</span>
                </div>
                <p className="mt-1 text-[10px] leading-relaxed text-dim">
                  {signalDescription}
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}