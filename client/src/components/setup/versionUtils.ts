import { ApiProblem } from '@/services/http'
import { toManilaInput } from '@/utils/manilaTime'

/** Helpers shared by the rules and mapping versions (ADR-0012, ADR-0013). */

export function asProblem(caught: unknown): ApiProblem {
  return caught instanceof ApiProblem ? caught : new ApiProblem(0, { detail: String(caught) })
}

/** The next whole hour in Manila, as a datetime-local value. */
export const nextHourInput = () => toManilaInput(Date.now() + 3600_000).slice(0, 14) + '00'
