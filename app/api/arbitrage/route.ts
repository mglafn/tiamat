import { NextResponse, type NextRequest } from "next/server"
import { tryUpstream } from "@/lib/proxy"
import { mockArbitrage } from "@/lib/mock-data"
import type { ArbitrageOpportunity } from "@/lib/types"

export const dynamic = "force-dynamic"

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams
  const minSpread = Number.parseFloat(sp.get("min_spread") ?? "2.00")
  const limit = Math.min(Number.parseInt(sp.get("limit") ?? "50", 10), 500)

  const upstream = await tryUpstream<ArbitrageOpportunity[]>(`/api/v1/arbitrage?min_spread=${minSpread}&limit=${limit}`)
  const data = upstream ?? mockArbitrage(Number.isFinite(minSpread) ? minSpread : 2, Number.isFinite(limit) ? limit : 50)
  return NextResponse.json(data)
}
