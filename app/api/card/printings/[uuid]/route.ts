import { NextResponse, type NextRequest } from "next/server"
import { tryUpstream } from "@/lib/proxy"
import { mockPrintings } from "@/lib/mock-data"
import type { CardVariant } from "@/lib/types"

export const dynamic = "force-dynamic"

export async function GET(_req: NextRequest, { params }: { params: Promise<{ uuid: string }> }) {
  const { uuid } = await params
  const upstream = await tryUpstream<CardVariant[]>(`/api/v1/card/printings/${uuid}`)
  const data = upstream ?? mockPrintings(uuid)
  return NextResponse.json(data)
}