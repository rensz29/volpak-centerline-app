import type { CorrelationResult, CorrelationStrength } from '@/types'

export function mean(values: readonly number[]): number {
  if (values.length === 0) return 0
  return values.reduce((sum, v) => sum + v, 0) / values.length
}

export function minimum(values: readonly number[]): number {
  return values.length === 0 ? 0 : Math.min(...values)
}

export function maximum(values: readonly number[]): number {
  return values.length === 0 ? 0 : Math.max(...values)
}

/** Sample standard deviation (n − 1), the right choice for measured process data. */
export function standardDeviation(values: readonly number[]): number {
  if (values.length < 2) return 0
  const avg = mean(values)
  const variance =
    values.reduce((sum, v) => sum + (v - avg) ** 2, 0) / (values.length - 1)
  return Math.sqrt(variance)
}

export function median(values: readonly number[]): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 0) {
    return ((sorted[mid - 1] ?? 0) + (sorted[mid] ?? 0)) / 2
  }
  return sorted[mid] ?? 0
}

/**
 * Pearson product-moment correlation of two equal-length series.
 * Returns 0 when either series has no variance, since correlation is undefined.
 */
export function pearson(xs: readonly number[], ys: readonly number[]): number {
  const n = Math.min(xs.length, ys.length)
  if (n < 2) return 0

  const xMean = mean(xs.slice(0, n))
  const yMean = mean(ys.slice(0, n))

  let numerator = 0
  let xSumSq = 0
  let ySumSq = 0

  for (let i = 0; i < n; i += 1) {
    const dx = (xs[i] ?? 0) - xMean
    const dy = (ys[i] ?? 0) - yMean
    numerator += dx * dy
    xSumSq += dx * dx
    ySumSq += dy * dy
  }

  const denominator = Math.sqrt(xSumSq * ySumSq)
  return denominator === 0 ? 0 : numerator / denominator
}

export interface LinearFit {
  slope: number
  intercept: number
}

/** Ordinary least-squares fit, used to draw the scatter chart's trend line. */
export function linearRegression(
  xs: readonly number[],
  ys: readonly number[],
): LinearFit {
  const n = Math.min(xs.length, ys.length)
  if (n < 2) return { slope: 0, intercept: 0 }

  const xMean = mean(xs.slice(0, n))
  const yMean = mean(ys.slice(0, n))

  let numerator = 0
  let denominator = 0
  for (let i = 0; i < n; i += 1) {
    const dx = (xs[i] ?? 0) - xMean
    numerator += dx * ((ys[i] ?? 0) - yMean)
    denominator += dx * dx
  }

  const slope = denominator === 0 ? 0 : numerator / denominator
  return { slope, intercept: yMean - slope * xMean }
}

export function correlationStrength(coefficient: number): CorrelationStrength {
  const r = Math.abs(coefficient)
  if (r >= 0.9) return 'very strong'
  if (r >= 0.7) return 'strong'
  if (r >= 0.5) return 'moderate'
  if (r >= 0.3) return 'weak'
  return 'negligible'
}

export function analyseCorrelation(
  xs: readonly number[],
  ys: readonly number[],
): CorrelationResult {
  const coefficient = pearson(xs, ys)
  const { slope, intercept } = linearRegression(xs, ys)
  const strength = correlationStrength(coefficient)

  return {
    coefficient,
    slope,
    intercept,
    sampleCount: Math.min(xs.length, ys.length),
    strength,
    direction:
      strength === 'negligible' ? 'none' : coefficient >= 0 ? 'positive' : 'negative',
  }
}

/** Plain-language reading of a coefficient, shown on the insight card. */
export function describeCorrelation(result: CorrelationResult): string {
  if (result.sampleCount < 3) {
    return 'Not enough overlapping samples to compute a reliable correlation.'
  }
  if (result.direction === 'none') {
    return 'No meaningful linear relationship — the two parameters vary independently across the selected data.'
  }
  const direction = result.direction === 'positive' ? 'increases' : 'decreases'
  return `As the X-axis parameter increases, the Y-axis parameter generally ${direction}. The relationship is ${result.strength}.`
}

/** Coefficient of determination — the share of variance the fit explains. */
export function rSquared(coefficient: number): number {
  return coefficient * coefficient
}
