import type { ParameterCode, ProcessSample, Shift } from '@/types'
import { skuTargets } from './parameters'

/* ==========================================================================
   Seeded pseudo-random generation
   ========================================================================== */

/** mulberry32 — small, fast, and good enough for fixture data. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Box–Muller transform: uniform noise into a standard normal. */
function makeNormal(random: () => number): () => number {
  return () => {
    const u1 = Math.max(random(), Number.EPSILON)
    const u2 = random()
    return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2)
  }
}

/** Rescale a series to mean 0, standard deviation 1. */
function standardize(values: readonly number[]): number[] {
  const n = values.length
  if (n === 0) return []
  const mean = values.reduce((sum, v) => sum + v, 0) / n
  const variance = values.reduce((sum, v) => sum + (v - mean) ** 2, 0) / n
  const sd = Math.sqrt(variance)
  if (sd === 0) return values.map(() => 0)
  return values.map((v) => (v - mean) / sd)
}

/**
 * Build a series correlating with `driver` at approximately `r`.
 *
 * For standardised, independent z₁ and z₂, the combination `r·z₁ + √(1−r²)·z₂`
 * has correlation r with z₁. Correlating on the *final standardised* series —
 * rather than on the noise term alone — is what makes the target correlation
 * survive: any drift already present in the driver is inherited through r
 * instead of diluting it.
 */
function correlatedSeries(
  driver: readonly number[],
  r: number,
  randn: () => number,
): number[] {
  const independentWeight = Math.sqrt(Math.max(0, 1 - r * r))
  return standardize(
    driver.map((z) => r * z + independentWeight * randn()),
  )
}

/** A slowly drifting, self-standardised series: process wander plus noise. */
function driftingSeries(
  length: number,
  cycles: number,
  amplitude: number,
  phase: number,
  randn: () => number,
): number[] {
  const raw: number[] = []
  for (let i = 0; i < length; i += 1) {
    const progress = length === 1 ? 0 : i / (length - 1)
    raw.push(amplitude * Math.sin(2 * Math.PI * cycles * progress + phase) + randn())
  }
  return standardize(raw)
}

/* ==========================================================================
   Per-parameter profile
   ========================================================================== */

interface NoiseProfile {
  /** Final standard deviation of the value, as a % of its target. */
  spreadPct: number
  /** Slow-drift amplitude, in units of the noise standard deviation. */
  driftAmplitude: number
  driftCycles: number
  /** Phase offset so independent parameters do not wander in lockstep. */
  phase: number
}

const NOISE: Record<ParameterCode, NoiseProfile> = {
  sealing_temperature: { spreadPct: 0.85, driftAmplitude: 0.9, driftCycles: 1.5, phase: 0 },
  hopper_pressure: { spreadPct: 2.6, driftAmplitude: 0.8, driftCycles: 1.2, phase: 1.9 },
  hopper_level: { spreadPct: 6.5, driftAmplitude: 1.1, driftCycles: 2.4, phase: 3.4 },
  discharge_weight: { spreadPct: 0.75, driftAmplitude: 0.6, driftCycles: 1.8, phase: 5.1 },
  machine_speed: { spreadPct: 2.5, driftAmplitude: 0.9, driftCycles: 0.9, phase: 2.7 },
  filling_pressure: { spreadPct: 3.0, driftAmplitude: 0.7, driftCycles: 1.4, phase: 4.4 },
  product_weight: { spreadPct: 0.95, driftAmplitude: 0.6, driftCycles: 1.8, phase: 0.8 },
  jaw_temperature: { spreadPct: 1.6, driftAmplitude: 0.8, driftCycles: 1.6, phase: 5.8 },
}

/**
 * Engineered correlation structure.
 *
 * Hopper pressure is the upstream cause: it pushes product through the auger,
 * so discharge weight follows it strongly, filling pressure moderately, and
 * hopper level only loosely. Machine speed is deliberately left independent so
 * the analytics page has a genuine "no relationship" case to report.
 */
const TARGET_CORRELATIONS = {
  pressureToDischarge: 0.8,
  pressureToLevel: 0.42,
  pressureToFilling: 0.6,
  sealingToJaw: 0.85,
  dischargeToProductWeight: 0.95,
} as const

/**
 * Operator setpoint drift: `machineId:parameterCode` → multiplier applied to the
 * target to produce the HMI value. Anything other than 1 means someone changed
 * the recipe on the panel and it was never reconciled with the centerline.
 */
const HMI_DRIFT: Record<string, number> = {
  'mac-1:hopper_pressure': 1.1, // 5.0 bar target dialled up to 5.5
  'mac-3:machine_speed': 1.06,
  'mac-5:sealing_temperature': 0.985,
  'mac-3:filling_pressure': 1.04,
}

/**
 * SKU schedule per machine. Filler A1 holds one SKU across the whole window
 * because it is the default analytics scope, and a changeover mid-window would
 * split the data into two scale regimes that distort any correlation computed
 * over it. The line-2 machines do change over, so SKU colouring stays
 * meaningful and the changeover itself is visible in the trend charts.
 */
const MACHINE_SKUS: Record<string, readonly [string, string]> = {
  'mac-1': ['sku-1', 'sku-1'],
  'mac-2': ['sku-1', 'sku-1'],
  'mac-3': ['sku-4', 'sku-3'],
  'mac-4': ['sku-4', 'sku-2'],
  'mac-5': ['sku-5', 'sku-5'],
}

/** Fraction of the window before the changeover, for machines that have one. */
const CHANGEOVER_AT = 0.6

const MACHINE_CONTEXT: Record<string, { lineId: string; factoryId: string }> = {
  'mac-1': { lineId: 'line-n1', factoryId: 'fac-north' },
  'mac-2': { lineId: 'line-n1', factoryId: 'fac-north' },
  'mac-3': { lineId: 'line-n2', factoryId: 'fac-north' },
  'mac-4': { lineId: 'line-n2', factoryId: 'fac-north' },
  'mac-5': { lineId: 'line-s1', factoryId: 'fac-south' },
}

/** Which parameters each machine actually carries a sensor for. */
const MACHINE_PARAMETERS: Record<string, readonly ParameterCode[]> = {
  'mac-1': [
    'sealing_temperature',
    'hopper_pressure',
    'hopper_level',
    'discharge_weight',
    'machine_speed',
    'filling_pressure',
    'product_weight',
    'jaw_temperature',
  ],
  'mac-2': ['sealing_temperature', 'machine_speed', 'jaw_temperature'],
  'mac-3': [
    'sealing_temperature',
    'hopper_pressure',
    'hopper_level',
    'discharge_weight',
    'machine_speed',
    'filling_pressure',
    'product_weight',
    'jaw_temperature',
  ],
  'mac-4': ['discharge_weight', 'machine_speed', 'product_weight'],
  'mac-5': [
    'sealing_temperature',
    'hopper_pressure',
    'hopper_level',
    'discharge_weight',
    'machine_speed',
    'filling_pressure',
    'product_weight',
  ],
}

/* ==========================================================================
   Timeline
   ========================================================================== */

const SAMPLE_COUNT = 60
const SAMPLE_INTERVAL_MS = 8 * 60 * 1000 // 8 minutes → an 8-hour shift window

/**
 * Anchored once at module load. Values are seeded and therefore stable, while
 * timestamps stay relative to the current session so "12m ago" reads as live
 * rather than as a stale fixture date.
 */
export const SESSION_NOW = Math.floor(Date.now() / 60_000) * 60_000
export const WINDOW_START = SESSION_NOW - (SAMPLE_COUNT - 1) * SAMPLE_INTERVAL_MS

function shiftForTimestamp(timestamp: number): Shift {
  const hour = new Date(timestamp).getHours()
  if (hour >= 6 && hour < 14) return 'A'
  if (hour >= 14 && hour < 22) return 'B'
  return 'C'
}

const DECIMALS: Record<ParameterCode, number> = {
  sealing_temperature: 1,
  hopper_pressure: 2,
  hopper_level: 1,
  discharge_weight: 1,
  machine_speed: 0,
  filling_pressure: 2,
  product_weight: 1,
  jaw_temperature: 1,
}

function roundTo(value: number, decimals: number): number {
  const factor = 10 ** decimals
  return Math.round(value * factor) / factor
}

/* ==========================================================================
   Sample generation
   ========================================================================== */

function generateForMachine(machineId: string, seed: number): ProcessSample[] {
  const random = mulberry32(seed)
  const randn = makeNormal(random)
  const context = MACHINE_CONTEXT[machineId]
  const skuPair = MACHINE_SKUS[machineId]
  const available = MACHINE_PARAMETERS[machineId]
  if (!context || !skuPair || !available) return []

  const availableSet = new Set<ParameterCode>(available)
  const n = SAMPLE_COUNT

  const drift = (code: ParameterCode): number[] => {
    const profile = NOISE[code]
    return driftingSeries(
      n,
      profile.driftCycles,
      profile.driftAmplitude,
      profile.phase + seed * 0.0001,
      randn,
    )
  }

  // Independent drivers, then everything that physically follows them.
  const zPressure = drift('hopper_pressure')
  const zSealing = drift('sealing_temperature')
  const zSpeed = drift('machine_speed')

  const zDischarge = correlatedSeries(
    zPressure,
    TARGET_CORRELATIONS.pressureToDischarge,
    randn,
  )
  const zLevel = correlatedSeries(zPressure, TARGET_CORRELATIONS.pressureToLevel, randn)
  const zFilling = correlatedSeries(
    zPressure,
    TARGET_CORRELATIONS.pressureToFilling,
    randn,
  )
  const zJaw = correlatedSeries(zSealing, TARGET_CORRELATIONS.sealingToJaw, randn)
  const zWeight = correlatedSeries(
    zDischarge,
    TARGET_CORRELATIONS.dischargeToProductWeight,
    randn,
  )

  const zByCode: Record<ParameterCode, readonly number[]> = {
    hopper_pressure: zPressure,
    sealing_temperature: zSealing,
    machine_speed: zSpeed,
    discharge_weight: zDischarge,
    hopper_level: zLevel,
    filling_pressure: zFilling,
    jaw_temperature: zJaw,
    product_weight: zWeight,
  }

  const samples: ProcessSample[] = []

  for (let i = 0; i < n; i += 1) {
    const timestamp = WINDOW_START + i * SAMPLE_INTERVAL_MS
    const skuId = i < n * CHANGEOVER_AT ? skuPair[0] : skuPair[1]
    const targets = skuTargets[skuId]
    if (!targets) continue

    const values = {} as ProcessSample['values']

    for (const code of Object.keys(zByCode) as ParameterCode[]) {
      const target = targets[code]
      const decimals = DECIMALS[code]
      const z = zByCode[code][i] ?? 0
      const hmi = target * (HMI_DRIFT[`${machineId}:${code}`] ?? 1)

      // A machine without the sensor, plus an occasional dropout elsewhere,
      // both surface as No Data.
      const hasSensor = availableSet.has(code)
      const dropout = random() < 0.012
      const actual =
        !hasSensor || dropout ? null : target * (1 + (z * NOISE[code].spreadPct) / 100)

      values[code] = {
        actual: actual === null ? null : roundTo(actual, decimals),
        hmi: roundTo(hmi, decimals),
        target: roundTo(target, decimals),
      }
    }

    samples.push({
      id: `${machineId}-${i}`,
      timestamp: new Date(timestamp).toISOString(),
      factoryId: context.factoryId,
      lineId: context.lineId,
      machineId,
      skuId,
      shift: shiftForTimestamp(timestamp),
      values,
    })
  }

  return samples
}

export interface PinnedReading {
  target: number
  hmi: number
  actual: number | null
}

/**
 * The showcase readings from the specification, used as the *current* reading
 * for Filler A1.
 *
 * They are applied to `parameterReadings` and appended as the final point of
 * that machine's trend chart, but are deliberately kept out of `processSamples`.
 * Hopper pressure at 5.7 bar sits more than five standard deviations above its
 * own generated series — exactly the excursion the demo needs the alarm panel to
 * show, and exactly the high-leverage outlier that would distort every
 * correlation computed over the historical record. Live reading and historical
 * series are therefore two separate things, which is also how a real historian
 * treats them.
 */
export const PINNED_READINGS: Partial<Record<ParameterCode, PinnedReading>> = {
  sealing_temperature: { target: 180, hmi: 180, actual: 182 }, // Warning
  hopper_pressure: { target: 5.0, hmi: 5.5, actual: 5.7 }, // Critical + setpoint drift
  hopper_level: { target: 75, hmi: 75, actual: 64 }, // Warning
  discharge_weight: { target: 500, hmi: 500, actual: 496 }, // Normal
  filling_pressure: { target: 2.4, hmi: 2.4, actual: null }, // No Data
  product_weight: { target: 502, hmi: 502, actual: 498.4 }, // Normal
  machine_speed: { target: 120, hmi: 120, actual: 118 }, // Normal
  jaw_temperature: { target: 165, hmi: 165, actual: 166.2 }, // Normal
}

/** The machine the pinned showcase readings belong to. */
export const PINNED_MACHINE_ID = 'mac-1'

const MACHINE_SEEDS: Record<string, number> = {
  'mac-1': 20_240_517,
  'mac-2': 71_338_902,
  'mac-3': 44_912_007,
  'mac-4': 98_017_453,
  'mac-5': 13_557_281,
}

function buildProcessSamples(): ProcessSample[] {
  const all: ProcessSample[] = []
  for (const [machineId, seed] of Object.entries(MACHINE_SEEDS)) {
    all.push(...generateForMachine(machineId, seed))
  }
  return all.sort((a, b) => a.timestamp.localeCompare(b.timestamp))
}

export const processSamples: ProcessSample[] = buildProcessSamples()

export { MACHINE_PARAMETERS, SAMPLE_COUNT, SAMPLE_INTERVAL_MS, DECIMALS }
