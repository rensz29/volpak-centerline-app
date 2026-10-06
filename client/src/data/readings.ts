import type { ParameterCode, ParameterReading } from '@/types'
import {
  MACHINE_PARAMETERS,
  PINNED_MACHINE_ID,
  PINNED_READINGS,
  processSamples,
} from './generate'
import { parameterByCode } from './parameters'
import { machines, mockOperators } from './plant'

/**
 * Current Digital Centerline readings, taken from the most recent process
 * sample for each machine. Deriving them rather than hand-writing a second
 * fixture guarantees the table value, the drawer's detail panel and the final
 * point of the trend chart all show the same number.
 */

/** Sensors known to be offline, forced to No Data regardless of the sample. */
const OFFLINE_SENSORS: ReadonlySet<string> = new Set([
  'mac-1:filling_pressure',
  'mac-5:hopper_level',
])

function buildReadings(): ParameterReading[] {
  const readings: ParameterReading[] = []

  for (const machine of machines) {
    const machineSamples = processSamples.filter((s) => s.machineId === machine.id)
    const latest = machineSamples.at(-1)
    const codes = MACHINE_PARAMETERS[machine.id]
    if (!latest || !codes) continue

    codes.forEach((code: ParameterCode, index) => {
      const definition = parameterByCode.get(code)
      // Showcase readings take precedence on the pinned machine; every other
      // reading is the latest generated sample.
      const pinned =
        machine.id === PINNED_MACHINE_ID ? PINNED_READINGS[code] : undefined
      const sample = pinned ?? latest.values[code]
      if (!definition) return

      const offline = OFFLINE_SENSORS.has(`${machine.id}:${code}`)

      // Stagger update times so the Last Updated column reads like a live feed
      // rather than a single batch write.
      const staggerMs = (index * 37 + machine.id.length * 11) * 1000
      const updatedAt = new Date(
        new Date(latest.timestamp).getTime() - staggerMs,
      ).toISOString()

      readings.push({
        id: `rdg-${machine.id}-${code}`,
        parameterId: definition.id,
        factoryId: latest.factoryId,
        lineId: latest.lineId,
        machineId: machine.id,
        skuId: latest.skuId,
        targetSetpoint: sample.target,
        hmiSetpoint: sample.hmi,
        actualValue: offline ? null : sample.actual,
        updatedAt,
        updatedBy: mockOperators[index % mockOperators.length] ?? 'System',
      })
    })
  }

  return readings
}

export const parameterReadings: ParameterReading[] = buildReadings()
