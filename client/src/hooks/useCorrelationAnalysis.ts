import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiProblem, analyticsApi } from '@/services/analyticsApi'
import type {
  AggregationCode,
  AnalyticsOptions,
  AnalyticsResult,
  BucketCode,
  GroupByCode,
  ShiftCode,
} from '@/types/analyticsApi'
import { toUtcIso } from '@/utils/manilaTime'

export interface AnalysisForm {
  x: string
  y: string
  fromMs: number
  toMs: number
  shift: ShiftCode
  bucket: BucketCode
  aggregation: AggregationCode
  groupBy: GroupByCode
  groupStats: boolean
}

export type AnalysisStatus = 'loading-options' | 'running' | 'done' | 'error'

/**
 * Start from the URL when it names an analysis, e.g.
 * ?x=P02.V1.setpoint&y=P02.V1.actual&hours=168&groupBy=SHIFT. A bare zone
 * ("P02.V1", the form before setpoints were added) means its actual value.
 */
function fromUrl(options: AnalyticsOptions, defaults: AnalysisForm): AnalysisForm {
  const q = new URLSearchParams(window.location.search)
  const channel = (key: string) => {
    const v = q.get(key)
    if (!v) return null
    const match = options.variables.find((o) => o.channel === v || o.channel === `${v}.actual`)
    return match?.channel ?? null
  }
  const pick = <T extends string>(key: string, allowed: { code: T }[]) => {
    const v = q.get(key)
    return allowed.find((o) => o.code === v)?.code ?? null
  }
  const hours = Number(q.get('hours'))
  const now = Date.now()
  return {
    x: channel('x') ?? defaults.x,
    y: channel('y') ?? defaults.y,
    fromMs: hours > 0 ? now - Math.min(hours, options.limits.maxRangeDays * 24) * 3_600_000 : defaults.fromMs,
    toMs: now,
    shift: pick('shift', options.shifts) ?? defaults.shift,
    bucket: pick('bucket', options.buckets) ?? defaults.bucket,
    aggregation: pick('aggregation', options.aggregations) ?? defaults.aggregation,
    groupBy: pick('groupBy', options.groupings) ?? defaults.groupBy,
    groupStats: q.get('groupStats') === '1',
  }
}

/**
 * Options, the query form and the latest result of the Analytics page.
 * A new run cancels the one in flight, so only the latest answer is shown.
 */
export function useCorrelationAnalysis() {
  const [options, setOptions] = useState<AnalyticsOptions | null>(null)
  const [form, setForm] = useState<AnalysisForm | null>(null)
  const [result, setResult] = useState<AnalyticsResult | null>(null)
  const [status, setStatus] = useState<AnalysisStatus>('loading-options')
  const [error, setError] = useState<ApiProblem | null>(null)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const inFlight = useRef<AbortController | null>(null)

  const run = useCallback(async (next: AnalysisForm) => {
    inFlight.current?.abort()
    const controller = new AbortController()
    inFlight.current = controller
    setStatus('running')
    setError(null)
    setStartedAt(Date.now())
    try {
      const answer = await analyticsApi.query(
        {
          from: toUtcIso(next.fromMs),
          to: toUtcIso(next.toMs),
          x: next.x,
          y: next.y,
          bucket: next.bucket,
          aggregation: next.aggregation,
          shift: next.shift,
          groupBy: next.groupBy,
          groupStats: next.groupStats,
        },
        controller.signal,
      )
      setResult(answer)
      setStatus('done')
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') return
      setError(
        caught instanceof ApiProblem
          ? caught
          : new ApiProblem(0, { title: 'Unexpected error', detail: String(caught) }),
      )
      setStatus('error')
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    analyticsApi
      .options(controller.signal)
      .then((loaded) => {
        setOptions(loaded)
        const now = Date.now()
        const initial: AnalysisForm = {
          x: loaded.defaults.x ?? loaded.variables[0]?.channel ?? '',
          y: loaded.defaults.y ?? loaded.variables[1]?.channel ?? '',
          fromMs: now - loaded.defaults.rangeHours * 3_600_000,
          toMs: now,
          shift: loaded.defaults.shift,
          bucket: loaded.defaults.bucket,
          aggregation: loaded.defaults.aggregation,
          groupBy: loaded.defaults.groupBy,
          groupStats: false,
        }
        const start = fromUrl(loaded, initial)
        setForm(start)
        void run(start)
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === 'AbortError') return
        setError(caught instanceof ApiProblem ? caught : new ApiProblem(0, { detail: String(caught) }))
        setStatus('error')
      })
    return () => {
      controller.abort()
      inFlight.current?.abort()
    }
  }, [run])

  const update = useCallback((patch: Partial<AnalysisForm>) => {
    setForm((current) => (current ? { ...current, ...patch } : current))
  }, [])

  return { options, form, update, run, result, status, error, startedAt }
}
