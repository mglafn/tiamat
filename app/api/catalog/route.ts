import { NextResponse } from "next/server"
import { tryUpstream, upstreamBase } from "@/lib/proxy"
import { mockCatalog } from "@/lib/mock-data"

export const dynamic = "force-dynamic"

export async function GET() {
  if (upstreamBase()) {
    // Actually check if the Python API has finished booting
    const health = await tryUpstream("/health")
    if (health) {
      return NextResponse.json({ source: "live", cards: [] })
    }
  }
  // Serve the mock names while waiting for FastAPI to boot
  return NextResponse.json({ source: "mock", cards: mockCatalog() })
}