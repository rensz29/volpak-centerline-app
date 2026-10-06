import type { ParameterCode, ParameterDefinition } from '@/types'

/**
 * The eight monitored centerline parameters.
 *
 * Tolerances are expressed as a percentage of the target setpoint and are tuned
 * so the seeded readings produce all four statuses on screen at once — a demo
 * that only ever shows green proves nothing about the status system.
 */
export const parameterDefinitions: ParameterDefinition[] = [
  {
    id: 'par-sealing-temp',
    code: 'sealing_temperature',
    name: 'Sealing Temperature',
    category: 'temperature',
    unit: '°C',
    description:
      'Temperature of the transverse sealing jaws. Running cold produces weak seals and leakers; running hot scorches the film and contaminates the jaw face.',
    minAllowed: 140,
    maxAllowed: 210,
    warningTolerancePct: 1,
    criticalTolerancePct: 3,
    decimals: 1,
    machineIds: ['mac-1', 'mac-2', 'mac-3', 'mac-5'],
  },
  {
    id: 'par-hopper-pressure',
    code: 'hopper_pressure',
    name: 'Hopper Pressure',
    category: 'pressure',
    unit: 'bar',
    description:
      'Pneumatic pressure applied to the product hopper. Drives dosing consistency; excess pressure over-packs the auger and inflates discharge weight.',
    minAllowed: 3,
    maxAllowed: 8,
    warningTolerancePct: 3,
    criticalTolerancePct: 8,
    decimals: 2,
    machineIds: ['mac-1', 'mac-3', 'mac-5'],
  },
  {
    id: 'par-hopper-level',
    code: 'hopper_level',
    name: 'Hopper Level',
    category: 'level',
    unit: '%',
    description:
      'Fill level of the product hopper as a percentage of usable volume. Low level lets head pressure fall away and starves the dosing auger.',
    minAllowed: 20,
    maxAllowed: 100,
    warningTolerancePct: 8,
    criticalTolerancePct: 20,
    decimals: 1,
    machineIds: ['mac-1', 'mac-3', 'mac-5'],
  },
  {
    id: 'par-discharge-weight',
    code: 'discharge_weight',
    name: 'Discharge Weight',
    category: 'output',
    unit: 'g',
    description:
      'Mass discharged per dosing cycle, measured at the auger outlet before the pack is formed.',
    minAllowed: 0,
    maxAllowed: 1200,
    warningTolerancePct: 1,
    criticalTolerancePct: 2.5,
    decimals: 1,
    machineIds: ['mac-1', 'mac-3', 'mac-4', 'mac-5'],
  },
  {
    id: 'par-machine-speed',
    code: 'machine_speed',
    name: 'Machine Speed',
    category: 'speed',
    unit: 'ppm',
    description:
      'Output rate in packs per minute. Running above the validated centerline shortens jaw dwell time and degrades seal integrity.',
    minAllowed: 40,
    maxAllowed: 220,
    warningTolerancePct: 4,
    criticalTolerancePct: 10,
    decimals: 0,
    machineIds: ['mac-1', 'mac-2', 'mac-3', 'mac-4', 'mac-5'],
  },
  {
    id: 'par-filling-pressure',
    code: 'filling_pressure',
    name: 'Filling Pressure',
    category: 'pressure',
    unit: 'bar',
    description:
      'Line pressure at the filling nozzle during the dose stroke. Governs fill rate and splash-back at the pack mouth.',
    minAllowed: 1,
    maxAllowed: 4,
    warningTolerancePct: 4,
    criticalTolerancePct: 9,
    decimals: 2,
    machineIds: ['mac-1', 'mac-3', 'mac-5'],
  },
  {
    id: 'par-product-weight',
    code: 'product_weight',
    name: 'Product Weight',
    category: 'quality',
    unit: 'g',
    description:
      'Finished pack weight recorded by the checkweigher. The legally declared quantity, and the parameter giveaway is measured against.',
    minAllowed: 0,
    maxAllowed: 1200,
    warningTolerancePct: 1.2,
    criticalTolerancePct: 3,
    decimals: 1,
    machineIds: ['mac-1', 'mac-3', 'mac-4', 'mac-5'],
  },
  {
    id: 'par-jaw-temp',
    code: 'jaw_temperature',
    name: 'Jaw Temperature',
    category: 'temperature',
    unit: '°C',
    description:
      'Longitudinal (back-seal) jaw temperature. Tracks alongside sealing temperature; a divergence between the two points to a failing heater cartridge.',
    minAllowed: 120,
    maxAllowed: 200,
    warningTolerancePct: 2,
    criticalTolerancePct: 5,
    decimals: 1,
    machineIds: ['mac-1', 'mac-2', 'mac-3'],
  },
]

export const parameterById = new Map(parameterDefinitions.map((p) => [p.id, p]))
export const parameterByCode = new Map<ParameterCode, ParameterDefinition>(
  parameterDefinitions.map((p) => [p.code, p]),
)

/** Nominal target for each parameter on a given SKU, used to seed readings. */
export const skuTargets: Record<string, Record<ParameterCode, number>> = {
  'sku-1': {
    sealing_temperature: 180,
    hopper_pressure: 5.0,
    hopper_level: 75,
    discharge_weight: 500,
    machine_speed: 120,
    filling_pressure: 2.4,
    product_weight: 502,
    jaw_temperature: 165,
  },
  'sku-2': {
    sealing_temperature: 176,
    hopper_pressure: 4.6,
    hopper_level: 70,
    discharge_weight: 250,
    machine_speed: 135,
    filling_pressure: 2.2,
    product_weight: 252,
    jaw_temperature: 160,
  },
  'sku-3': {
    sealing_temperature: 188,
    hopper_pressure: 5.8,
    hopper_level: 80,
    discharge_weight: 1000,
    machine_speed: 95,
    filling_pressure: 2.8,
    product_weight: 1004,
    jaw_temperature: 172,
  },
  'sku-4': {
    sealing_temperature: 168,
    hopper_pressure: 4.2,
    hopper_level: 65,
    discharge_weight: 18,
    machine_speed: 180,
    filling_pressure: 1.9,
    product_weight: 18.4,
    jaw_temperature: 152,
  },
  'sku-5': {
    sealing_temperature: 164,
    hopper_pressure: 3.9,
    hopper_level: 60,
    discharge_weight: 6,
    machine_speed: 150,
    filling_pressure: 1.7,
    product_weight: 6.2,
    jaw_temperature: 148,
  },
}
