/**
 * lib/economics.ts
 * -----------------
 * Unit-economics decomposition engine.
 *
 * Decomposes a projected exit price into an ordered waterfall of fees, costs,
 * and condition haircuts to arrive at a risk-adjusted net payout.
 */

export interface EconInputs {
  /** Projected sell price at the 7-day horizon (the top of the waterfall). */
  exitPrice: number
  /** Current acquisition close before landed costs. */
  acqPrice: number
  /** TCGplayer seller tier — Pro pays a lower commission rate. */
  pro: boolean
  /** Sales tax rate applied to the taxable base (e.g. 0.075 for 7.5%). */
  taxRate: number
  /** Outbound freight per unit (amortized across a batch shipment). */
  freightPerUnit: number
  /** Condition-downgrade risk haircut multiplier in [0.80, 1.00]; 1 = no risk. */
  kappa: number
  /** Minimum acceptable net ROI %, the accumulate/hold hurdle. */
  hurdlePct: number
}

export interface WaterfallStep {
  key: string
  label: string
  /** Signed delta applied to the running balance ($). Negative = deduction. */
  delta: number
  /** Running balance AFTER this step. */
  balance: number
  kind: 'start' | 'fee' | 'cost' | 'risk' | 'result'
  /** Short human formula/annotation, e.g. "8.95% × $12.40". */
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
  /** Total fee load as a percentage of exit price. */
  feeLoadPct: number
}

const PRO_COMMISSION = 0.0895
const NONPRO_COMMISSION = 0.1025
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

/** Payout side: exit price minus all Direct/SYP fees and condition haircut. */
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
    note: `${(PROCESSING_RATE * 100).toFixed(1)}% × taxed total`,
  })

  bal -= PER_ORDER_FEE
  steps.push({ key: 'order', label: 'Per-Order Fee', delta: -PER_ORDER_FEE, balance: bal, kind: 'fee', note: 'flat / shipment' })

  bal -= freightPerUnit
  steps.push({ key: 'freight', label: 'Outbound Freight', delta: -freightPerUnit, balance: bal, kind: 'cost', note: 'amortized / unit' })

  // Condition-downgrade risk haircut
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

/** Cost side: acquisition price built up into a landed basis. */
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

  const hub = 0.012 * acqPrice + 0.05
  bal += hub
  steps.push({ key: 'hub', label: 'Hub Handling', delta: hub, balance: bal, kind: 'cost', note: 'grade + intake' })

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