import { NextResponse } from "next/server"
import { tryUpstream, upstreamBase } from "@/lib/proxy"
import { mockHealth } from "@/lib/mock-data"
import type { HealthCheck } from "@/lib/types"

export const dynamic = "force-dynamic"

export async function GET() {
  const upstream = await tryUpstream<HealthCheck>("/health")
  const data = upstream ?? mockHealth()
  return NextResponse.json({ ...data, source: upstream ? "live" : "mock" satisfies string })
}

export function HEAD() {
  return new NextResponse(null, { headers: { "x-source": upstreamBase() ? "live" : "mock" } })
}
