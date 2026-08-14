import { NextResponse, type NextRequest } from "next/server"
import { tryUpstream } from "@/lib/proxy"
import { mockSearch } from "@/lib/mock-data"
import type { CardSearchResult } from "@/lib/types"

export const dynamic = "force-dynamic"

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams
  const name = sp.get("name") ?? ""
  const limit = Math.min(Number.parseInt(sp.get("limit") ?? "20", 10), 100)

  if (name.length < 2) {
    return NextResponse.json([] as CardSearchResult[])
  }

  const upstream = await tryUpstream<CardSearchResult[]>(
    `/api/v1/search?name=${encodeURIComponent(name)}&limit=${limit}`,
  )
  const data = upstream ?? mockSearch(name, Number.isFinite(limit) ? limit : 20)
  return NextResponse.json(data)
}
