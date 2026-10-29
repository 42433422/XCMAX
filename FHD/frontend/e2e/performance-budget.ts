export function positiveBudget(value: string | undefined, fallback: number): number {
  const budget = value === undefined || value === '' ? fallback : Number(value)
  if (!Number.isFinite(budget) || budget <= 0) throw new Error(`Invalid performance budget: ${value}`)
  return budget
}

/** The observation timeout may be longer; it never changes the pass threshold. */
export function assertWithinBudget(elapsedMs: number, budgetMs: number, label: string): void {
  if (!Number.isFinite(elapsedMs) || elapsedMs < 0 || elapsedMs > budgetMs) {
    throw new Error(`${label}: ${elapsedMs}ms exceeds ${budgetMs}ms budget`)
  }
}

export function latencyPercentile(samples: number[], percentile: number): number {
  if (samples.length < 20 || samples.some((value) => !Number.isFinite(value) || value < 0)) {
    throw new Error('Latency distribution requires at least 20 valid measured samples')
  }
  if (percentile <= 0 || percentile > 100) throw new Error('Invalid percentile')
  const sorted = [...samples].sort((a, b) => a - b)
  return sorted[Math.ceil((percentile / 100) * sorted.length) - 1]
}
