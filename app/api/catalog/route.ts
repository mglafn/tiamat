import { NextResponse } from "next/server"
import { upstreamBase } from "@/lib/proxy"
import { mockCatalog } from "@/lib/mock-data"

export const dynamic = "force-dynamic"

// Name resolution for arbitrage rows (which carry only a uuid). In live mode
// the upstream has no bulk catalog endpoint, so the client falls back to the
// truncated uuid; in mock mode we return the full catalog.
export async function GET() {
  if (upstreamBase()) {
    return NextResponse.json({ source: "live", cards: [] })
  }
  return NextResponse.json({ source: "mock", cards: mockCatalog() })
}
