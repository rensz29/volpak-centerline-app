import { mockAlarms } from '@/data/alarms'
import { processSamples } from '@/data/generate'
import { parameterDefinitions } from '@/data/parameters'
import {
  currentUser,
  factories,
  machines,
  productionLines,
  skus,
} from '@/data/plant'
import { parameterReadings } from '@/data/readings'
import { mockSetpointHistory } from '@/data/setpointHistory'
import type {
  Alarm,
  Factory,
  Machine,
  ParameterDefinition,
  ParameterReading,
  ProcessSample,
  ProductionLine,
  SetpointChange,
  Sku,
  User,
} from '@/types'

/**
 * Frontend mock service.
 *
 * Every screen reads through this module rather than importing from `src/data`
 * directly, so Phase 2 can replace each function body with a `fetch` call
 * without touching a single component. The deliberate latency also means the
 * loading skeletons are exercised for real instead of being decorative.
 */

const DEFAULT_LATENCY_MS = 260

function delay<T>(payload: T, ms = DEFAULT_LATENCY_MS): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(payload), ms)
  })
}

/** Defensive copy so callers holding results cannot mutate the fixtures. */
function clone<T>(value: T): T {
  return structuredClone(value)
}

export const mockApi = {
  getFactories(): Promise<Factory[]> {
    return delay(clone(factories), 120)
  },

  getProductionLines(): Promise<ProductionLine[]> {
    return delay(clone(productionLines), 120)
  },

  getMachines(): Promise<Machine[]> {
    return delay(clone(machines), 120)
  },

  getSkus(): Promise<Sku[]> {
    return delay(clone(skus), 120)
  },

  getCurrentUser(): Promise<User> {
    return delay(clone(currentUser), 60)
  },

  getParameterDefinitions(): Promise<ParameterDefinition[]> {
    return delay(clone(parameterDefinitions))
  },

  getParameterReadings(): Promise<ParameterReading[]> {
    return delay(clone(parameterReadings))
  },

  getAlarms(): Promise<Alarm[]> {
    return delay(clone(mockAlarms))
  },

  getSetpointHistory(): Promise<SetpointChange[]> {
    return delay(clone(mockSetpointHistory))
  },

  getProcessSamples(): Promise<ProcessSample[]> {
    return delay(clone(processSamples), 320)
  },
}

export type MockApi = typeof mockApi
