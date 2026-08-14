// Resolves the upstream FastAPI base URL. When unset, routes fall back to
// the deterministic mock dataset so the terminal is fully functional standalone.
export function upstreamBase(): string | null {
  const url = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL
  return url ? url.replace(/\/$/, "") : null
}

// Attempts an upstream fetch. Returns null on any failure so the caller can
// gracefully serve mock data instead of erroring the whole terminal.
export async function tryUpstream<T>(path: string): Promise<T | null> {
  const base = upstreamBase()
  if (!base) return null
  try {
    const res = await fetch(`${base}${path}`, {
      headers: { accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return null
    return (await res.json()) as T
  } catch {
    return null
  }
}
