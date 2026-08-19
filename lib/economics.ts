/**
 * lib/economics.ts
 * -----------------
 * Unit-economics decomposition engine with exact fee modeling.
 */

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

const PRO_COMMISSION = 0.0895
const NONPRO_COMMISSION = 0.1075 // Exact standard marketplace commission
const PROCESSING_RATE = 0.025
const PER_ORDER_FEE = 1.12
const COMMISSION_CAP = 75.0

function round(n: number, d = 2): number {
  const f = 10 ** d
  return Math.round(n * f) / f
}

function fmt(n: number): string {
  return `$${n.toFixed(2)}`
}

export function computeExitWaterfall(inp: EconInputs): { steps: WaterfallStep[]; netPayout: number } {
  const { exitPrice, pro, taxRate, freightPerUnit, kappa } = inp
  const steps: WaterfallStep[] = []
  let bal = exitPrice

  steps.push({ key: 'gross', label: 'Projected Exit', delta: exitPrice, balance: bal, kind: 'start' })

  const commissionRate = pro ? PRO_COMMISSION : NONPRO_COMMISSION
  const commission = Math.min(exitPrice * commissionRate, COMMISSION_CAP)
  bal -= commission
  steps.push({
    key: 'commission',
    label: pro ? 'Seller Fee (Pro)' : 'Seller Fee (Non-Pro)',
    delta: -commission,
    balance: bal,
    kind: 'fee',
    note: `${(commissionRate * 100).toFixed(2)}% × ${fmt(exitPrice)}`,
  })

  const processing = exitPrice * (1 + taxRate) * PROCESSING_RATE
  bal -= processing
  steps.push({
    key: 'processing',
    label: 'Payment Processing',
    delta: -processing,
    balance: bal,
    kind: 'fee',
    note: `${(PROCESSING_RATE * 100).toFixed(1)}% × gross`,
  })

  bal -= PER_ORDER_FEE
  steps.push({ key: 'order', label: 'Per-Order Fee', delta: -PER_ORDER_FEE, balance: bal, kind: 'fee', note: 'flat / order' })

  bal -= freightPerUnit
  steps.push({ key: 'freight', label: 'Outbound Freight', delta: -freightPerUnit, balance: bal, kind: 'cost', note: 'amortized batch' })

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
  return { steps, netPayout: round(bal) }
}

export function computeLandedBasis(inp: EconInputs): { steps: WaterfallStep[]; landedBasis: number } {
  const { acqPrice, taxRate } = inp
  const steps: WaterfallStep[] = []
  let bal = acqPrice

  steps.push({ key: 'acq', label: 'Acquisition Close', delta: acqPrice, balance: bal, kind: 'start' })

  const tax = acqPrice * taxRate
  bal += tax
  steps.push({ key: 'tax', label: 'Sales Tax', delta: tax, balance: bal, kind: 'cost', note: `${(taxRate * 100).toFixed(1)}%` })

  const inbound = acqPrice < 5.0 ? 0.99 : 0.15
  bal += inbound
  steps.push({ key: 'inbound', label: 'Inbound Postage', delta: inbound, balance: bal, kind: 'cost', note: acqPrice < 5 ? '<$5 tier' : '≥$5 tier' })

  //Flat $0.012 amortized freight per card to Louisville hub
  const hubFreight = 0.012
  bal += hubFreight
  steps.push({ key: 'hub', label: 'Hub Freight', delta: hubFreight, balance: bal, kind: 'cost', note: 'bulk freight' })

  steps.push({ key: 'landed', label: 'Landed Basis', delta: 0, balance: bal, kind: 'result' })
  return { steps, landedBasis: round(bal) }
}

export function runEconomics(inp: EconInputs): EconResult {
  const { steps, netPayout } = computeExitWaterfall(inp)
  const { steps: landedSteps, landedBasis } = computeLandedBasis(inp)

  const netProfit = round(netPayout - landedBasis)
  const netRoiPct = landedBasis > 0 ? round((netProfit / landedBasis) * 100) : 0
  const grossMarginPct = netPayout > 0 ? round((netProfit / netPayout) * 100) : 0
  const totalFees = inp.exitPrice - netPayout
  const feeLoadPct = inp.exitPrice > 0 ? round((totalFees / inp.exitPrice) * 100) : 0

  const payoutPerDollar = inp.exitPrice > 0 ? netPayout / inp.exitPrice : 0
  const fixedDrag = inp.exitPrice - netPayout - inp.exitPrice * (1 - payoutPerDollar)
  const breakevenExit = payoutPerDollar > 0 ? round((landedBasis + fixedDrag) / payoutPerDollar) : 0

  return {
    steps,
    landedSteps,
    exitPrice: round(inp.exitPrice),
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