export function usd(n: number, opts?: { compact?: boolean }): string {
  if (opts?.compact && Math.abs(n) >= 1000) {
    return `$${(n / 1000).toFixed(2)}K`
  }
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function pct(n: number, withSign = true): string {
  const s = withSign && n > 0 ? "+" : ""
  return `${s}${n.toFixed(2)}%`
}

export function signClass(n: number): string {
  if (n > 0) return "text-up"
  if (n < 0) return "text-down"
  return "text-muted-foreground"
}

export function shortUuid(uuid: string): string {
  return uuid.slice(0, 4) + "-" + uuid.slice(-4)
}
