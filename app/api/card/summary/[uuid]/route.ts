import { NextResponse, type NextRequest } from "next/server"
import { tryUpstream } from "@/lib/proxy"
import { mockSummary } from "@/lib/mock-data"
import type { CardMarketSummary } from "@/lib/types"

export const dynamic = "force-dynamic"

export async function GET(_req: NextRequest, { params }: { params: Promise<{ uuid: string }> }) {
  const { uuid } = await params
  const upstream = await tryUpstream<CardMarketSummary>(`/api/v1/card/summary/${uuid}`)
  const data = upstream ?? mockSummary(uuid)
  if (!data) {
    return NextResponse.json({ detail: "No pricing records found." }, { status: 404 })
  }
  return NextResponse.json(data)
}
