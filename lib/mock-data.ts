/**
 * Deterministic mock data generator used for fallback demo mode when the backend is offline.
 * Seeded PRNG ensures identical fixture values across renders.
 */

import type {
  ArbitrageOpportunity,
  CardMarketSummary,
  CardSearchResult,
  CardVariant,
  HealthCheck,
  PredictionResponse,
  PriceHistoryPoint,
} from "./types"

function hashSeed(str: string): number {
  let h = 2166136261
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

function mulberry32(seed: number) {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function round(n: number, d = 2): number {
  const f = 10 ** d
  return Math.round(n * f) / f
}

interface Seed {
  name: string
  set_code: string
  base: number
  finish: "normal" | "foil" | "etched"
  vol: number
  collector_number?: string
  edhrec_rank?: number
}

const SEEDS: Seed[] = [
  { name: "Ragavan, Nimble Pilferer", set_code: "MH2", base: 46.0, finish: "normal", vol: 0.9, collector_number: "138", edhrec_rank: 42 },
  { name: "Sheoldred, the Apocalypse", set_code: "DMU", base: 72.0, finish: "normal", vol: 0.7, collector_number: "107", edhrec_rank: 18 },
  { name: "Force of Will", set_code: "EMA", base: 63.5, finish: "normal", vol: 0.6, collector_number: "49", edhrec_rank: 35 },
  { name: "Orcish Bowmasters", set_code: "LTR", base: 40.2, finish: "normal", vol: 1.0, collector_number: "103", edhrec_rank: 12 },
  { name: "The One Ring", set_code: "LTR", base: 58.0, finish: "normal", vol: 1.1, collector_number: "246", edhrec_rank: 8 },
  { name: "Mox Diamond", set_code: "STH", base: 680.0, finish: "foil", vol: 0.5, collector_number: "138", edhrec_rank: 110 },
  { name: "Demonic Tutor", set_code: "STA", base: 115.0, finish: "etched", vol: 0.8, collector_number: "90", edhrec_rank: 4 },
  { name: "Jeweled Lotus", set_code: "CMR", base: 85.0, finish: "etched", vol: 1.2, collector_number: "319", edhrec_rank: 25 },
  { name: "Underworld Breach", set_code: "THB", base: 15.1, finish: "foil", vol: 1.4, collector_number: "161", edhrec_rank: 84 },
  { name: "Grief", set_code: "MH2", base: 18.2, finish: "normal", vol: 1.2, collector_number: "87", edhrec_rank: 320 },
  { name: "Fable of the Mirror-Breaker", set_code: "NEO", base: 22.4, finish: "normal", vol: 0.8, collector_number: "141", edhrec_rank: 95 },
  { name: "Wrenn and Six", set_code: "MH1", base: 61.0, finish: "normal", vol: 0.7, collector_number: "217", edhrec_rank: 450 },
  { name: "Ancient Tomb", set_code: "TPR", base: 88.0, finish: "normal", vol: 0.6, collector_number: "236", edhrec_rank: 14 },
  { name: "Scalding Tarn", set_code: "MH2", base: 24.5, finish: "normal", vol: 0.5, collector_number: "254", edhrec_rank: 22 },
  { name: "Ragavan, Nimble Pilferer", set_code: "MUL", base: 132.0, finish: "etched", vol: 1.0, collector_number: "86", edhrec_rank: 42 },
  { name: "Slickshot Show-Off", set_code: "OTJ", base: 12.8, finish: "normal", vol: 1.3, collector_number: "145", edhrec_rank: 610 },
  { name: "Vein Ripper", set_code: "MKM", base: 33.5, finish: "normal", vol: 1.5, collector_number: "110", edhrec_rank: 890 },
  { name: "Urza's Saga", set_code: "MH2", base: 42.0, finish: "normal", vol: 0.9, collector_number: "259", edhrec_rank: 15 },
  { name: "Solitude", set_code: "MH2", base: 44.0, finish: "normal", vol: 0.8, collector_number: "32", edhrec_rank: 140 },
  { name: "Elesh Norn, Mother of Machines", set_code: "ONE", base: 28.0, finish: "normal", vol: 0.9, collector_number: "218", edhrec_rank: 29 },
  { name: "Bloodstained Mire", set_code: "KTK", base: 21.0, finish: "normal", vol: 0.5, collector_number: "230", edhrec_rank: 31 },
  { name: "Nadu, Winged Wisdom", set_code: "MH3", base: 9.4, finish: "normal", vol: 1.6, collector_number: "193", edhrec_rank: 105 },
  { name: "Phlage, Titan of Fire's Fury", set_code: "MH3", base: 34.0, finish: "normal", vol: 1.1, collector_number: "197", edhrec_rank: 412 },
  { name: "Emrakul, the Aeons Torn", set_code: "2X2", base: 76.0, finish: "etched", vol: 0.7, collector_number: "348", edhrec_rank: 380 },
  { name: "Liliana of the Veil", set_code: "MM3", base: 19.9, finish: "normal", vol: 0.6, collector_number: "76", edhrec_rank: 215 },
  { name: "Misty Rainforest", set_code: "MH2", base: 26.5, finish: "normal", vol: 0.5, collector_number: "250", edhrec_rank: 19 },
]

const VENDORS = ["tcgplayer", "cardkingdom", "starcitygames"]

function makeUuid(seed: Seed, i: number): string {
  const h1 = hashSeed(`${seed.name}|${seed.set_code}|${seed.finish}|${i}`).toString(16).padStart(8, "0")
  const h2 = hashSeed(`${h1}_mid`).toString(16).padStart(8, "0")
  const h3 = hashSeed(`${h2}_end`).toString(16).padStart(8, "0")
  const h4 = hashSeed(`${h3}_tail`).toString(16).padStart(8, "0")
  return `${h1}-${h2.slice(0, 4)}-4${h2.slice(4, 7)}-a${h3.slice(1, 4)}-${h3.slice(4, 8)}${h4.slice(0, 8)}`
}

export interface CatalogEntry {
  uuid: string
  seed: Seed
}

export const CATALOG: CatalogEntry[] = SEEDS.map((seed, i) => ({
  uuid: makeUuid(seed, i),
  seed,
}))

const BY_UUID = new Map(CATALOG.map((c) => [c.uuid, c]))
const TODAY = "2026-08-18"

interface Metrics {
  current: number
  sma7: number
  sma30: number
  dailyReturn: number
  floor: number
  ceiling: number
  avg: number
  variants: number
}

function metricsFor(entry: CatalogEntry): Metrics {
  const rnd = mulberry32(hashSeed(entry.uuid))
  const base = entry.seed.base
  const drift = (rnd() - 0.42) * entry.seed.vol
  const current = round(base * (1 + drift * 0.14))
  const sma7 = round(current * (1 - (rnd() - 0.5) * 0.05))
  const sma30 = round(current * (1 - (rnd() - 0.5) * 0.11))
  const dailyReturn = round((rnd() - 0.5) * 6, 2)
  const spreadBand = base * (0.06 + rnd() * 0.1)
  const floor = round(current - spreadBand)
  const ceiling = round(current + spreadBand * (0.8 + rnd()))
  const avg = round((floor + ceiling + current) / 3)
  const variants = 4 + Math.floor(rnd() * 9)
  return { current, sma7, sma30, dailyReturn, floor, ceiling, avg, variants }
}

function predict(m: Metrics, entry: CatalogEntry): { pred: number; gainPct: number; maeDollars: number } {
  const momentum = (m.sma7 - m.sma30) / Math.max(m.sma30, 1)
  const rnd = mulberry32(hashSeed(entry.uuid + "pred"))
  const gainPct = round(momentum * 100.0 * 0.85 + (rnd() - 0.45) * 6.0, 2)
  
  let pred = round(Math.max(0.01, m.current * (1 + gainPct / 100.0)))
  // Dead-zone clamping ($2.50 - $2.67 -> $2.49)
  if (pred >= 2.50 && pred <= 2.67) {
    pred = 2.49
  }
  
  const maeDollars = round(m.current * 0.048, 2)
  return { pred, gainPct, maeDollars }
}

export function mockHealth(): HealthCheck {
  return { status: "healthy", db_connected: true, model_loaded: true }
}

export function mockHistory(uuid: string, days = 60): PriceHistoryPoint[] {
  const entry = BY_UUID.get(uuid)
  const basePrice = entry?.seed.base ?? 25.0
  const rnd = mulberry32(hashSeed(uuid + "hist_feed"))
  
  const rawPrices: number[] = []
  let cur = basePrice * (0.94 + rnd() * 0.12)
  for (let i = 0; i < days; i++) {
    const shock = (rnd() - 0.49) * basePrice * 0.03
    cur = Math.max(0.25, cur + shock)
    rawPrices.push(round(cur))
  }
  
  const sma = (arr: number[], idx: number, win: number) => {
    const start = Math.max(0, idx - win + 1)
    const slice = arr.slice(start, idx + 1)
    return round(slice.reduce((a, b) => a + b, 0) / slice.length)
  }

  const baseDate = new Date(TODAY)
  return rawPrices.map((p, i) => {
    const d = new Date(baseDate)
    d.setDate(d.getDate() - (days - 1 - i))
    const prev = i > 0 ? rawPrices[i - 1] : p
    const dailyReturn = prev > 0 ? round(((p - prev) / prev) * 100, 2) : 0.0

    return {
      price_date: d.toISOString().split("T")[0],
      price: p,
      sma_7: sma(rawPrices, i, 7),
      sma_30: sma(rawPrices, i, 30),
      daily_return_pct: dailyReturn,
    }
  })
}

export function mockPrintings(uuid: string): CardVariant[] {
  const entry = BY_UUID.get(uuid)
  if (!entry) return []
  const cardName = entry.seed.name
  return CATALOG.filter((c) => c.seed.name === cardName).map((c) => {
    const m = metricsFor(c)
    const rnd = mulberry32(hashSeed(c.uuid + "print"))
    const num = c.seed.collector_number ?? String(100 + Math.floor(rnd() * 350))
    const rank = c.seed.edhrec_rank ?? (15 + Math.floor(rnd() * 2500))
    return {
      uuid: c.uuid,
      set_code: c.seed.set_code,
      collector_number: num,
      floor_price: m.floor,
      edhrec_rank: rank,
    }
  })
}

export function mockArbitrage(minSpread: number, limit: number): ArbitrageOpportunity[] {
  const rows: ArbitrageOpportunity[] = CATALOG.map((entry) => {
    const m = metricsFor(entry)
    const rnd = mulberry32(hashSeed(entry.uuid + "arb_feed"))
    const tcg = round(m.current * (0.95 + rnd() * 0.04))
    const ckBuylist = round(tcg * (1.18 + rnd() * 0.18))
    
    // Landed basis ($0.99 for <$5, $0.15 for >=$5, 7.5% tax, $0.09 CK outbound batch freight)
    const inboundPostage = tcg < 5.00 ? 0.99 : 0.15
    const costBasis = tcg * 1.075 + inboundPostage + 0.09
    const ckCreditPayout = ckBuylist * 1.30
    const netSpread = round(ckCreditPayout - costBasis)
    const pct = costBasis > 0 ? round((netSpread / costBasis) * 100) : 0

    return {
      uuid: entry.uuid,
      name: entry.seed.name,
      set_code: entry.seed.set_code,
      collector_number: entry.seed.collector_number,
      price_date: TODAY,
      finish: entry.seed.finish,
      tcg_price: tcg,
      ck_price: ckBuylist,
      price_spread: netSpread,
      spread_pct: pct,
    }
  })
  return rows
    .filter((r) => r.price_spread >= minSpread)
    .sort((a, b) => b.price_spread - a.price_spread)
    .slice(0, limit)
}

export function mockForecast(uuid: string, vendor: string, finish: string): PredictionResponse | null {
  const entry = BY_UUID.get(uuid)
  if (!entry) return null
  const m = metricsFor(entry)
  const { pred, gainPct, maeDollars } = predict(m, entry)
  const normalized = ["nonfoil", "regular"].includes(finish.toLowerCase()) ? "normal" : finish.toLowerCase()

  return {
    uuid,
    vendor,
    finish: normalized,
    current_price: m.current,
    predicted_7d_price: pred,
    predicted_gain_pct: gainPct,
    model_mae: maeDollars,
    directional_accuracy_pct: 68.4,
  }
}

export function mockSummary(uuid: string): CardMarketSummary | null {
  const entry = BY_UUID.get(uuid)
  if (!entry) return null
  const m = metricsFor(entry)
  const { pred, gainPct } = predict(m, entry)
  const rnd = mulberry32(hashSeed(uuid + "summary_vendor"))
  const rank = entry.seed.edhrec_rank ?? (25 + Math.floor(rnd() * 1800))

  return {
    uuid,
    name: entry.seed.name,
    set_code: entry.seed.set_code,
    collector_number: entry.seed.collector_number ?? String(100 + Math.floor(rnd() * 350)),
    edhrec_rank: rank,
    latest_price_date: TODAY,
    total_market_variants: m.variants,
    floor_price: m.floor,
    avg_price: m.avg,
    ceiling_price: m.ceiling,
    primary_vendor: VENDORS[Math.floor(rnd() * VENDORS.length)],
    primary_finish: entry.seed.finish,
    predicted_7d_price: pred,
    predicted_gain_pct: gainPct,
  }
}

export function mockSearch(name: string, limit: number): CardSearchResult[] {
  const q = name.toLowerCase()
  const results: CardSearchResult[] = CATALOG.filter((e) => e.seed.name.toLowerCase().includes(q)).map((entry) => {
    const m = metricsFor(entry)
    return {
      uuid: entry.uuid,
      name: entry.seed.name,
      set_code: entry.seed.set_code,
      collector_number: entry.seed.collector_number,
      finish: entry.seed.finish,
      floor_price: m.floor,
      avg_price: m.avg,
      vendor_count: 2 + Math.floor(mulberry32(hashSeed(entry.uuid + "vc_feed"))() * 3),
    }
  })
  return results.sort((a, b) => b.floor_price - a.floor_price).slice(0, limit)
}

export function mockCatalog() {
  return CATALOG.map((e) => ({ uuid: e.uuid, name: e.seed.name, set_code: e.seed.set_code }))
}

// Add to lib/mock-data.ts

import type { BacktestResponse } from "./types"

export function mockBacktest(hurdle = 10.0, tau = 0.90, filterMode = "exp_roi"): BacktestResponse {
  const dates = [
    "2026-07-24", "2026-07-26", "2026-07-28", "2026-07-30", 
    "2026-08-01", "2026-08-03", "2026-08-05"
  ]

  return {
    status: "success",
    params: {
      min_net_roi_pct: hurdle,
      tau,
      filter_mode: filterMode,
      sort_by: "exp_roi",
      sizing: "flat",
      top_daily: 0,
      is_pro: true,
    },
    summary: {
      total_trades: 6,
      win_trades: 5,
      loss_trades: 1,
      win_rate: 83.3,
      total_capital: 86.80,
      total_net_profit: 8.94,
      portfolio_roi: 10.30,
      avg_trade_roi: 18.27,
      avg_kelly: 0.382,
      profit_factor: 2.44,
      test_start_date: "2026-07-24",
      test_end_date: "2026-08-05",
      test_universe_count: 994912,
    },
    ablation: {
      naive_trades: 24,
      naive_win_rate: 45.8,
      naive_capital: 348.50,
      naive_profit: -14.20,
      naive_roi: -4.07,
      alpha_cash: 23.14,
      alpha_roi_bps: 1437.0,
      capital_saved: 261.70,
      capital_saved_pct: 75.1,
      vetoed_losses_avoided: 23.14,
    },
    equity_curve: [
      { date: "2026-07-24", active_cum_profit: 0.00, naive_cum_profit: 0.00 },
      { date: "2026-07-26", active_cum_profit: 3.50, naive_cum_profit: -4.10 },
      { date: "2026-07-28", active_cum_profit: 4.80, naive_cum_profit: -8.30 },
      { date: "2026-07-30", active_cum_profit: 9.60, naive_cum_profit: -3.20 },
      { date: "2026-08-01", active_cum_profit: 7.20, naive_cum_profit: -11.50 },
      { date: "2026-08-03", active_cum_profit: 8.40, naive_cum_profit: -9.80 },
      { date: "2026-08-05", active_cum_profit: 8.94, naive_cum_profit: -14.20 },
    ],
    top_trades: [
      {
        uuid: "land-tax-leg",
        name: "Land Tax",
        set_code: "LEG",
        collector_number: "26",
        finish: "normal",
        price_date: "2026-07-26",
        current_price: 22.40,
        basis: 25.07,
        realized_exit_payout: 33.09,
        actual_future_price: 38.50,
        pred_magnitude: 28.5,
        move_prob: 0.94,
        kelly_fraction: 0.45,
        allocated_units: 1,
        total_profit: 8.02,
        net_roi_pct: 32.0,
        is_win: true,
      },
      {
        uuid: "ancient-den-mrd",
        name: "Ancient Den",
        set_code: "MRD",
        collector_number: "278",
        finish: "normal",
        price_date: "2026-07-28",
        current_price: 5.90,
        basis: 7.51,
        realized_exit_payout: 12.68,
        actual_future_price: 15.00,
        pred_magnitude: 34.0,
        move_prob: 0.92,
        kelly_fraction: 0.40,
        allocated_units: 1,
        total_profit: 5.16,
        net_roi_pct: 68.7,
        is_win: true,
      },
      {
        uuid: "reflecting-pool-wc98",
        name: "Reflecting Pool",
        set_code: "WC98",
        collector_number: "328",
        finish: "normal",
        price_date: "2026-07-30",
        current_price: 6.05,
        basis: 7.65,
        realized_exit_payout: 8.90,
        actual_future_price: 11.20,
        pred_magnitude: 16.5,
        move_prob: 0.91,
        kelly_fraction: 0.30,
        allocated_units: 1,
        total_profit: 1.25,
        net_roi_pct: 16.3,
        is_win: true,
      },
    ],
    worst_trades: [
      {
        uuid: "land-tax-leg-loss",
        name: "Land Tax",
        set_code: "LEG",
        collector_number: "26",
        finish: "normal",
        price_date: "2026-08-01",
        current_price: 29.30,
        basis: 32.49,
        realized_exit_payout: 26.29,
        actual_future_price: 31.00,
        pred_magnitude: 14.2,
        move_prob: 0.90,
        kelly_fraction: 0.22,
        allocated_units: 1,
        total_profit: -6.20,
        net_roi_pct: -19.1,
        is_win: false,
      }
    ],
    vetoed_traps: [
      {
        uuid: "brainstorm-ema",
        name: "Brainstorm",
        set_code: "EMA",
        collector_number: "40",
        finish: "normal",
        price_date: "2026-07-26",
        current_price: 0.80,
        basis: 1.85,
        realized_exit_payout: 1.13,
        actual_future_price: 2.25,
        pred_magnitude: 18.4,
        move_prob: 0.92,
        kelly_fraction: 0.0,
        allocated_units: 1,
        total_profit: -0.72,
        net_roi_pct: -38.9,
        is_win: false,
        veto_reason: "Fee Cliff (Sub-$2.50 Tier)",
      },
      {
        uuid: "dark-ritual-sta",
        name: "Dark Ritual",
        set_code: "STA",
        collector_number: "26",
        finish: "normal",
        price_date: "2026-07-31",
        current_price: 1.35,
        basis: 2.45,
        realized_exit_payout: 1.60,
        actual_future_price: 2.55,
        pred_magnitude: 14.0,
        move_prob: 0.90,
        kelly_fraction: 0.0,
        allocated_units: 1,
        total_profit: -0.85,
        net_roi_pct: -34.6,
        is_win: false,
        veto_reason: "Dead-Zone [$2.50, $2.67]",
      }
    ]
  }
}