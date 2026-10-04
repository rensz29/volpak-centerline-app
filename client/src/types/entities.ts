/** Plant hierarchy: Factory → ProductionLine → Machine, plus the SKUs run on them. */

export interface Factory {
  id: string
  name: string
  code: string
  location: string
  timezone: string
}

export type LineStatus = 'running' | 'idle' | 'changeover' | 'down'

export interface ProductionLine {
  id: string
  factoryId: string
  name: string
  code: string
  status: LineStatus
  /** Nominal throughput in packs per minute, used for Overview context. */
  ratedSpeedPpm: number
}

export type MachineStatus = 'running' | 'idle' | 'maintenance' | 'offline'

export interface Machine {
  id: string
  lineId: string
  factoryId: string
  name: string
  code: string
  model: string
  type: string
  status: MachineStatus
  commissionedOn: string
}

export interface Sku {
  id: string
  code: string
  name: string
  productType: string
  packFormat: string
  targetWeightG: number
}

export interface User {
  id: string
  name: string
  initials: string
  role: string
  email: string
  shift: Shift
}

export type Shift = 'A' | 'B' | 'C'

export const SHIFTS: readonly Shift[] = ['A', 'B', 'C']

export const SHIFT_LABELS: Record<Shift, string> = {
  A: 'Shift A · 06:00–14:00',
  B: 'Shift B · 14:00–22:00',
  C: 'Shift C · 22:00–06:00',
}
