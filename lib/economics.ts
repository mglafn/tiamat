/**
 * lib/economics.ts
 * -----------------
 * Unit-economics decomposition engine with exact TCGplayer Direct fee modeling.
 */

import { FEE_CONSTANTS } from './constants'
import type { ArbitrageOpportunity } from './types'

export type LandedChannel = 'direct' | 'spatial_ck' | 'buyer'

export interface EconInputs {
  exitPrice: number
  acqPrice: number
  pro: boolean
  taxRate: number
  freightPerUnit: number
  kappa: number
  hurdlePct: number
}

export interface WaterfallStep {
  key: string
  label: string
  delta: number
  balance: number
  kind: 'start' | 'fee' | 'cost' | 'risk' | 'result'
  note?: string
}

export interface EconResult {
  steps: WaterfallStep[]
  exitPrice: number
  netPayout: number
  landedBasis: number
  landedSteps: WaterfallStep[]
  netProfit: number
  netRoiPct: number
  grossMarginPct: number
  clearsHurdle: boolean
  breakevenExit: number
  feeLoadPct: number
}

export function roundHalfEven(n: number, decimals = 2): number {
  const factor = 10 ** decimals
  const scaled = Number((n * factor).toFixed(6))
  const floored = Math.floor(scaled)
  const frac = scaled - floored
  if (Math.abs(frac - 0.5) < 1e-6) {
    return (floored % 2 === 0 ? floored : floored + 1) / factor
  }
  return Math.round(scaled) / factor
}

function fmt(n: number): string {
  return `$${n.toFixed(2)}`
}

export function computeLandedBasisAmount(
  acqPrice: number,
  taxRate: number = FEE_CONSTANTS.DEFAULT_TAX_RATE,
  channel: LandedChannel = 'direct'
): number {
  const inbound =
    acqPrice < FEE_CONSTANTS.INBOUND_POSTAGE_THRESHOLD_USD
      ? FEE_CONSTANTS.INBOUND_POSTAGE_LOW_USD
      : FEE_CONSTANTS.INBOUND_POSTAGE_HIGH_USD
  const channelFreight =
    channel === 'direct'
      ? FEE_CONSTANTS.HUB_FREIGHT_USD
      : channel === 'spatial_ck'
        ? FEE_CONSTANTS.OUTBOUND_BATCH_FREIGHT_USD
        : 0
  return acqPrice * (1 + taxRate) + inbound + channelFreight
}

export function computeStagedTotals(rows: ArbitrageOpportunity[]): {
  stagedBasis: number
  stagedExpectedPayout: number
  blendedROI: number
} {
  const stagedBasis = rows.reduce((acc, r) => {
    const ask = r.tcg_price || 0
    if (ask <= 0) return acc
    return acc + computeLandedBasisAmount(ask, FEE_CONSTANTS.DEFAULT_TAX_RATE, 'spatial_ck')
  }, 0)

  const stagedExpectedPayout = rows.reduce(
    (acc, r) => acc + (r.ck_price || 0) * FEE_CONSTANTS.STORE_CREDIT_MULTIPLIER,
    0
  )

  const blendedROI =
    stagedBasis > 0 ? ((stagedExpectedPayout - stagedBasis) / stagedBasis) * 100 : 0

  return { stagedBasis, stagedExpectedPayout, blendedROI }
}

export function computeExitWaterfall(inp: EconInputs): { steps: WaterfallStep[]; netPayout: number } {
  const { exitPrice, pro, taxRate, freightPerUnit, kappa } = inp
  const steps: WaterfallStep[] = []

  if (exitPrice < FEE_CONSTANTS.DIRECT_FLOOR_USD) {
    steps.push({ key: 'gross', label: 'Projected Exit', delta: exitPrice, balance: exitPrice, kind: 'start' })
    steps.push({ key: 'floor', label: 'Below Direct Floor (<$0.40)', delta: -exitPrice, balance: 0, kind: 'fee', note: 'ineligible' })
    steps.push({ key: 'net', label: 'Net Payout', delta: 0, balance: 0, kind: 'result' })
    return { steps, netPayout: 0 }
  }

  const deadZoneMax = pro
    ? FEE_CONSTANTS.DIRECT_DEAD_ZONE_MAX_PRO
    : FEE_CONSTANTS.DIRECT_DEAD_ZONE_MAX
  const effectiveExit =
    exitPrice >= FEE_CONSTANTS.DIRECT_DEAD_ZONE_MIN && exitPrice <= deadZoneMax
      ? FEE_CONSTANTS.DIRECT_TIER1_MAX_USD
      : exitPrice
  let bal = effectiveExit

  steps.push({
    key: 'gross',
    label: effectiveExit !== exitPrice ? 'Clamped Exit ($2.49)' : 'Projected Exit',
    delta: effectiveExit,
    balance: bal,
    kind: 'start',
  })

  if (effectiveExit < FEE_CONSTANTS.DIRECT_DEAD_ZONE_MIN) {
    const flatTierFee = roundHalfEven(effectiveExit * FEE_CONSTANTS.DIRECT_TIER1_RATE)
    bal = Math.max(0, roundHalfEven(effectiveExit - flatTierFee))
    steps.push({
      key: 'commission',
      label: 'Direct Fee (<$2.50 Flat 50%)',
      delta: -flatTierFee,
      balance: bal,
      kind: 'fee',
      note: '50% flat fee (commission waived)',
    })
  } else {
    const commission = Math.min(
      effectiveExit * FEE_CONSTANTS.DIRECT_COMMISSION,
      FEE_CONSTANTS.COMMISSION_CAP_USD
    )
    bal -= commission
    steps.push({
      key: 'commission',
      label: 'Direct Commission',
      delta: -commission,
      balance: bal,
      kind: 'fee',
      note: `${(FEE_CONSTANTS.DIRECT_COMMISSION * 100).toFixed(2)}% × ${fmt(effectiveExit)}`,
    })

    let proFee = 0
    if (pro) {
      proFee = Math.min(effectiveExit * FEE_CONSTANTS.PRO_FEE, FEE_CONSTANTS.COMMISSION_CAP_USD)
      bal -= proFee
      steps.push({
        key: 'pro',
        label: 'TCGplayer Pro Fee',
        delta: -proFee,
        balance: bal,
        kind: 'fee',
        note: `${(FEE_CONSTANTS.PRO_FEE * 100).toFixed(2)}% × ${fmt(effectiveExit)}`,
      })
    }

    const processing = effectiveExit * (1 + taxRate) * FEE_CONSTANTS.PROCESSING_RATE
    bal -= processing
    steps.push({
      key: 'processing',
      label: 'Payment Processing',
      delta: -processing,
      balance: bal,
      kind: 'fee',
      note: `${(FEE_CONSTANTS.PROCESSING_RATE * 100).toFixed(1)}% × gross`,
    })

    const platformFeesRounded = roundHalfEven(
      commission + proFee + processing + FEE_CONSTANTS.DIRECT_FIXED_USD
    )
    bal = Math.max(0, roundHalfEven(effectiveExit - platformFeesRounded))
    steps.push({
      key: 'order',
      label: 'Direct Fixed Fee',
      delta: -FEE_CONSTANTS.DIRECT_FIXED_USD,
      balance: bal,
      kind: 'fee',
      note: `$${FEE_CONSTANTS.DIRECT_FIXED_USD.toFixed(2)} / unit`,
    })
  }

  bal -= freightPerUnit
  steps.push({
    key: 'freight',
    label: 'Outbound Freight',
    delta: -freightPerUnit,
    balance: bal,
    kind: 'cost',
    note: 'amortized batch',
  })

  const preHaircut = bal
  const haircut = preHaircut * (1 - kappa)
  bal -= haircut
  steps.push({
    key: 'kappa',
    label: 'Condition Haircut (κ)',
    delta: -haircut,
    balance: bal,
    kind: 'risk',
    note: `κ = ${(kappa * 100).toFixed(1)}%`,
  })

  steps.push({ key: 'net', label: 'Net Payout', delta: 0, balance: bal, kind: 'result' })
  return { steps, netPayout: Math.max(0, roundHalfEven(bal)) }
}

export function computeLandedBasis(inp: EconInputs): { steps: WaterfallStep[]; landedBasis: number } {
  const { acqPrice, taxRate } = inp
  const steps: WaterfallStep[] = []
  let bal = acqPrice

  steps.push({ key: 'acq', label: 'Acquisition Close', delta: acqPrice, balance: bal, kind: 'start' })

  const tax = acqPrice * taxRate
  bal += tax
  steps.push({
    key: 'tax',
    label: 'Sales Tax',
    delta: tax,
    balance: bal,
    kind: 'cost',
    note: `${(taxRate * 100).toFixed(1)}%`,
  })

  const inbound =
    acqPrice < FEE_CONSTANTS.INBOUND_POSTAGE_THRESHOLD_USD
      ? FEE_CONSTANTS.INBOUND_POSTAGE_LOW_USD
      : FEE_CONSTANTS.INBOUND_POSTAGE_HIGH_USD
  bal += inbound
  steps.push({
    key: 'inbound',
    label: 'Inbound Postage',
    delta: inbound,
    balance: bal,
    kind: 'cost',
    note: acqPrice < FEE_CONSTANTS.INBOUND_POSTAGE_THRESHOLD_USD ? '<$5 tier' : '≥$5 tier',
  })

  bal += FEE_CONSTANTS.HUB_FREIGHT_USD
  steps.push({
    key: 'hub',
    label: 'Hub Freight',
    delta: FEE_CONSTANTS.HUB_FREIGHT_USD,
    balance: bal,
    kind: 'cost',
    note: 'bulk freight',
  })

  steps.push({ key: 'landed', label: 'Landed Basis', delta: 0, balance: bal, kind: 'result' })
  return { steps, landedBasis: roundHalfEven(bal) }
}

export function runEconomics(inp: EconInputs): EconResult {
  const { steps, netPayout } = computeExitWaterfall(inp)
  const { steps: landedSteps, landedBasis } = computeLandedBasis(inp)

  const netProfit = roundHalfEven(netPayout - landedBasis)
  const netRoiPct = landedBasis > 0 ? roundHalfEven((netProfit / landedBasis) * 100) : 0
  const grossMarginPct = netPayout > 0 ? roundHalfEven((netProfit / netPayout) * 100) : 0
  const deadZoneMax = inp.pro
    ? FEE_CONSTANTS.DIRECT_DEAD_ZONE_MAX_PRO
    : FEE_CONSTANTS.DIRECT_DEAD_ZONE_MAX
  const effectiveExit =
    inp.exitPrice >= FEE_CONSTANTS.DIRECT_DEAD_ZONE_MIN && inp.exitPrice <= deadZoneMax
      ? FEE_CONSTANTS.DIRECT_TIER1_MAX_USD
      : inp.exitPrice
  const platformFees = steps
    .filter((s) => s.kind === 'fee')
    .reduce((acc, s) => acc + Math.abs(s.delta), 0)
  const feeLoadPct = effectiveExit > 0 ? roundHalfEven((platformFees / effectiveExit) * 100) : 0

  const safeKappa = inp.kappa > 0 ? inp.kappa : 1
  const requiredPreKappa = landedBasis / safeKappa + inp.freightPerUnit
  const tier1Breakeven = requiredPreKappa / (1 - FEE_CONSTANTS.DIRECT_TIER1_RATE)
  const proRate = inp.pro ? FEE_CONSTANTS.PRO_FEE : 0
  const processingRate = (1 + inp.taxRate) * FEE_CONSTANTS.PROCESSING_RATE
  const tier2Denom = 1 - FEE_CONSTANTS.DIRECT_COMMISSION - proRate - processingRate
  const tier2Uncapped =
    tier2Denom > 0 ? (requiredPreKappa + FEE_CONSTANTS.DIRECT_FIXED_USD) / tier2Denom : 0
  const commissionCapTrigger = FEE_CONSTANTS.COMMISSION_CAP_USD / FEE_CONSTANTS.DIRECT_COMMISSION
  let tier2Breakeven = tier2Uncapped
  if (tier2Uncapped > commissionCapTrigger) {
    const cappedDirectDenom = 1 - proRate - processingRate
    const cappedDirect =
      cappedDirectDenom > 0
        ? (requiredPreKappa + FEE_CONSTANTS.DIRECT_FIXED_USD + FEE_CONSTANTS.COMMISSION_CAP_USD) /
          cappedDirectDenom
        : 0
    const proCapTrigger = FEE_CONSTANTS.COMMISSION_CAP_USD / FEE_CONSTANTS.PRO_FEE
    if (inp.pro && cappedDirect > proCapTrigger) {
      const bothCappedDenom = 1 - processingRate
      tier2Breakeven =
        bothCappedDenom > 0
          ? (requiredPreKappa +
              FEE_CONSTANTS.DIRECT_FIXED_USD +
              2 * FEE_CONSTANTS.COMMISSION_CAP_USD) /
            bothCappedDenom
          : 0
    } else {
      tier2Breakeven = cappedDirect
    }
  }
  const breakevenExit =
    tier1Breakeven < FEE_CONSTANTS.DIRECT_DEAD_ZONE_MIN
      ? roundHalfEven(tier1Breakeven)
      : roundHalfEven(tier2Breakeven)

  return {
    steps,
    landedSteps,
    exitPrice: roundHalfEven(inp.exitPrice),
    netPayout,
    landedBasis,
    netProfit,
    netRoiPct,
    grossMarginPct,
    clearsHurdle: netRoiPct >= inp.hurdlePct,
    breakevenExit,
    feeLoadPct,
  }
}