import { NextResponse, type NextRequest } from "next/server"
import { tryUpstream } from "@/lib/proxy"
import { mockForecast } from "@/lib/mock-data"
import type { PredictionResponse } from "@/lib/types"

export const dynamic = "force-dynamic"

export async function GET(req: NextRequest, { params }: { params: Promise<{ uuid: string }> }) {
  const { uuid } = await params
  const sp = req.nextUrl.searchParams
  const vendor = sp.get("vendor") ?? "tcgplayer"
  const finish = sp.get("finish") ?? "normal"

  const upstream = await tryUpstream<PredictionResponse>(
    `/api/v1/forecast/${uuid}?vendor=${encodeURIComponent(vendor)}&finish=${encodeURIComponent(finish)}`,
  )
  const data = upstream ?? mockForecast(uuid, vendor, finish)
  if (!data) {
    return NextResponse.json({ detail: "Card metrics not found." }, { status: 404 })
  }
  return NextResponse.json(data)
}
