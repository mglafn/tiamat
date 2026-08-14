import type {
  ArbitrageOpportunity,
  CardMarketSummary,
  CardSearchResult,
  CardVariant,
  HealthCheck,
  PredictionResponse,
} from "./types"

// ---------------------------------------------------------------------------
// Deterministic pseudo-random helpers (stable output per key => stable UI)
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// Catalog — realistic secondary-market Magic singles
// ---------------------------------------------------------------------------
interface Seed {
  name: string
  set_code: string
  base: number // approximate market value (USD)
  finish: "normal" | "foil"
  vol: number // volatility factor
}

const SEEDS: Seed[] = [
  { name: "Ragavan, Nimble Pilferer", set_code: "MH2", base: 46.0, finish: "normal", vol: 0.9 },
  { name: "Sheoldred, the Apocalypse", set_code: "DMU", base: 72.0, finish: "normal", vol: 0.7 },
  { name: "Force of Will", set_code: "EMA", base: 63.5, finish: "normal", vol: 0.6 },
  { name: "Orcish Bowmasters", set_code: "LTR", base: 40.2, finish: "normal", vol: 1.0 },
  { name: "The One Ring", set_code: "LTR", base: 58.0, finish: "normal", vol: 1.1 },
  { name: "Mox Diamond", set_code: "STH", base: 680.0, finish: "foil", vol: 0.5 },
  { name: "Underworld Breach", set_code: "THB", base: 15.1, finish: "foil", vol: 1.4 },
  { name: "Grief", set_code: "MH2", base: 18.2, finish: "normal", vol: 1.2 },
  { name: "Fable of the Mirror-Breaker", set_code: "NEO", base: 22.4, finish: "normal", vol: 0.8 },
  { name: "Wrenn and Six", set_code: "MH1", base: 61.0, finish: "normal", vol: 0.7 },
  { name: "Ancient Tomb", set_code: "TPR", base: 88.0, finish: "normal", vol: 0.6 },
  { name: "Scalding Tarn", set_code: "MH2", base: 24.5, finish: "normal", vol: 0.5 },
  { name: "Ragavan, Nimble Pilferer", set_code: "MUL", base: 132.0, finish: "foil", vol: 1.0 },
  { name: "Slickshot Show-Off", set_code: "OTJ", base: 12.8, finish: "normal", vol: 1.3 },
  { name: "Vein Ripper", set_code: "MKM", base: 33.5, finish: "normal", vol: 1.5 },
  { name: "Urza's Saga", set_code: "MH2", base: 42.0, finish: "normal", vol: 0.9 },
  { name: "Solitude", set_code: "MH2", base: 44.0, finish: "normal", vol: 0.8 },
  { name: "Elesh Norn, Mother of Machines", set_code: "ONE", base: 28.0, finish: "normal", vol: 0.9 },
  { name: "Bloodstained Mire", set_code: "KTK", base: 21.0, finish: "normal", vol: 0.5 },
  { name: "Nadu, Winged Wisdom", set_code: "MH3", base: 9.4, finish: "normal", vol: 1.6 },
  { name: "Phlage, Titan of Fire's Fury", set_code: "MH3", base: 34.0, finish: "normal", vol: 1.1 },
  { name: "Emrakul, the Aeons Torn", set_code: "MOR", base: 76.0, finish: "normal", vol: 0.7 },
  { name: "Liliana of the Veil", set_code: "MM3", base: 19.9, finish: "normal", vol: 0.6 },
  { name: "Misty Rainforest", set_code: "MH2", base: 26.5, finish: "normal", vol: 0.5 },
]

const VENDORS = ["tcgplayer", "cardkingdom", "starcitygames", "coolstuffinc"]

function makeUuid(seed: Seed, i: number): string {
  const h = hashSeed(`${seed.name}|${seed.set_code}|${seed.finish}|${i}`).toString(16).padStart(8, "0")
  const h2 = hashSeed(`${h}salt`).toString(16).padStart(8, "0")
  return `${h.slice(0, 8)}-${h2.slice(0, 4)}-4${h2.slice(4, 7)}-${h2.slice(0, 4)}`
}

export interface CatalogEntry {
  uuid: string
  seed: Seed
}

// Stable catalog built once at module load.
export const CATALOG: CatalogEntry[] = SEEDS.map((seed, i) => ({
  uuid: makeUuid(seed, i),
  seed,
}))

const BY_UUID = new Map(CATALOG.map((c) => [c.uuid, c]))

const TODAY = "2026-08-14"

// ---------------------------------------------------------------------------
// Per-card derived metrics (deterministic)
// ---------------------------------------------------------------------------
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
  const dailyReturn = round((rnd() - 0.5) * 6, 3)
  const spreadBand = base * (0.06 + rnd() * 0.1)
  const floor = round(current - spreadBand)
  const ceiling = round(current + spreadBand * (0.8 + rnd()))
  const avg = round((floor + ceiling + current) / 3)
  const variants = 4 + Math.floor(rnd() * 9)
  return { current, sma7, sma30, dailyReturn, floor, ceiling, avg, variants }
}

// XGBoost-style projection: blend of SMA momentum + mean reversion.
function predict(m: Metrics, entry: CatalogEntry): { pred: number; mae: number } {
  const momentum = (m.sma7 - m.sma30) / Math.max(m.sma30, 1)
  const rnd = mulberry32(hashSeed(entry.uuid + "pred"))
  const projected = m.current * (1 + momentum * 1.6 + (rnd() - 0.45) * 0.05)
  return { pred: round(projected), mae: 0.182 }
}

// ---------------------------------------------------------------------------
// Endpoint builders
// ---------------------------------------------------------------------------
export function mockHealth(): HealthCheck {
  return { status: "healthy", db_connected: true, model_loaded: true }
}

export function mockPrintings(uuid: string): CardVariant[] {
  const entry = BY_UUID.get(uuid)
  if (!entry) return []
  const cardName = entry.seed.name
  return CATALOG.filter((c) => c.seed.name === cardName).map((c) => ({
    uuid: c.uuid,
    set_code: c.seed.set_code,
  }))
}

export function mockArbitrage(minSpread: number, limit: number): ArbitrageOpportunity[] {
  const rows: ArbitrageOpportunity[] = CATALOG.map((entry) => {
    const m = metricsFor(entry)
    const rnd = mulberry32(hashSeed(entry.uuid + "arb"))
    const tcg = round(m.current * (0.96 + rnd() * 0.03))
    const ck = round(tcg * (1.08 + rnd() * 0.24))
    const spread = round(ck - tcg)
    const pct = round((spread / tcg) * 100)
    return {
      uuid: entry.uuid,
      name: entry.seed.name,
      set_code: entry.seed.set_code,
      price_date: TODAY,
      finish: entry.seed.finish,
      tcg_price: tcg,
      ck_price: ck,
      price_spread: spread,
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
  const { pred, mae } = predict(m, entry)
  const gain = m.current > 0 ? round(((pred - m.current) / m.current) * 100) : 0
  const normalized = ["nonfoil", "regular"].includes(finish.toLowerCase()) ? "normal" : finish.toLowerCase()
  return {
    uuid,
    vendor,
    finish: normalized,
    current_price: m.current,
    predicted_7d_price: pred,
    predicted_gain_pct: gain,
    model_mae: mae,
  }
}

export function mockSummary(uuid: string): CardMarketSummary | null {
  const entry = BY_UUID.get(uuid)
  if (!entry) return null
  const m = metricsFor(entry)
  const { pred } = predict(m, entry)
  const gain = m.current > 0 ? round(((pred - m.current) / m.current) * 100) : 0
  const rnd = mulberry32(hashSeed(uuid + "vendor"))
  return {
    uuid,
    name: entry.seed.name,
    set_code: entry.seed.set_code,
    latest_price_date: TODAY,
    total_market_variants: m.variants,
    floor_price: m.floor,
    avg_price: m.avg,
    ceiling_price: m.ceiling,
    primary_vendor: VENDORS[Math.floor(rnd() * VENDORS.length)],
    primary_finish: entry.seed.finish,
    predicted_7d_price: pred,
    predicted_gain_pct: gain,
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
      finish: entry.seed.finish,
      floor_price: m.floor,
      avg_price: m.avg,
      vendor_count: 2 + Math.floor(mulberry32(hashSeed(entry.uuid + "vc"))() * 3),
    }
  })
  return results.sort((a, b) => b.floor_price - a.floor_price).slice(0, limit)
}

// Catalog lookup for client-side name resolution (arbitrage rows carry only uuid).
export function mockCatalog() {
  return CATALOG.map((e) => ({ uuid: e.uuid, name: e.seed.name, set_code: e.seed.set_code }))
}