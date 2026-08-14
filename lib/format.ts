// lib/format.ts

export function usd(n: number | null | undefined, opts?: { compact?: boolean }): string {
  if (n == null || typeof n !== "number" || isNaN(n)) {
    return "$0.00"
  }
  if (opts?.compact && Math.abs(n) >= 1000) {
    return `$${(n / 1000).toFixed(2)}K`
  }
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function pct(n: number | null | undefined, withSign = true): string {
  if (n == null || typeof n !== "number" || isNaN(n)) {
    return "0.00%"
  }
  const s = withSign && n > 0 ? "+" : ""
  return `${s}${n.toFixed(2)}%`
}

export function signClass(n: number | null | undefined): string {
  if (n == null || typeof n !== "number") return "text-muted-foreground"
  if (n > 0) return "text-up"
  if (n < 0) return "text-down"
  return "text-muted-foreground"
}

export function shortUuid(uuid: string | null | undefined): string {
  if (!uuid) return "0000-0000"
  return uuid.slice(0, 4) + "-" + uuid.slice(-4)
}