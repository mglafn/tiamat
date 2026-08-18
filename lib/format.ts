/**
 * lib/format.ts
 * -------------
 * Number formatting and presentation helpers for currency, percentages, and identifiers.
 */

export function usd(
  n: number | null | undefined,
  opts?: { compact?: boolean; fallback?: string }
): string {
  if (n == null || typeof n !== 'number' || isNaN(n)) {
    return opts?.fallback ?? '—'
  }
  if (opts?.compact && Math.abs(n) >= 1000) {
    return `$${(n / 1000).toFixed(2)}K`
  }
  return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function pct(
  n: number | null | undefined,
  withSign = true,
  opts?: { fallback?: string }
): string {
  if (n == null || typeof n !== 'number' || isNaN(n)) {
    return opts?.fallback ?? '—'
  }
  const s = withSign && n > 0 ? '+' : ''
  return `${s}${n.toFixed(2)}%`
}

export function signClass(n: number | null | undefined): string {
  if (n == null || typeof n !== 'number') return 'text-muted-foreground'
  if (n > 0) return 'text-up'
  if (n < 0) return 'text-down'
  return 'text-muted-foreground'
}

export function shortUuid(uuid: string | null | undefined): string {
  if (!uuid) return '0000-0000'
  return uuid.slice(0, 4) + '-' + uuid.slice(-4)
}

/** Signed currency with explicit +/- prefix, for waterfall deltas. */
export function signedUsd(n: number | null | undefined): string {
  if (n == null || typeof n !== 'number' || isNaN(n)) return '—'
  const sign = n > 0 ? '+' : n < 0 ? '−' : ''
  return `${sign}$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** Compact integer count, e.g. 1240 -> 1.24K. */
export function count(n: number | null | undefined): string {
  if (n == null || typeof n !== 'number' || isNaN(n)) return '—'
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}K`
  return String(Math.round(n))
}