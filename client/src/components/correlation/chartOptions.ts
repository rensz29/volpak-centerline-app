import type { EChartsCoreOption } from 'echarts/core'

import type { AnalyticsResult, AnalyticsVariable } from '@/types/analyticsApi'
import { formatManilaFull, formatManilaShort } from '@/utils/manilaTime'

/**
 * ECharts options for the two tabs (ANA-15). Both render the same paired
 * buckets from the api, so Scatter and Trend never disagree.
 */

export interface Palette {
  ink: string
  inkSoft: string
  inkMuted: string
  line: string
  lineSoft: string
  surface: string
  brand: string
  fit: string
  series: [string, string]
  groups: string[]
  other: string
}

function cssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

/** Colours come from the design tokens in index.css, so charts follow the app's palette. */
export function readPalette(): Palette {
  return {
    ink: cssVar('--color-ink', '#0f172a'),
    inkSoft: cssVar('--color-ink-soft', '#475569'),
    inkMuted: cssVar('--color-ink-muted', '#94a3b8'),
    line: cssVar('--color-line', '#e2e8f0'),
    lineSoft: cssVar('--color-line-soft', '#f1f5f9'),
    surface: cssVar('--color-surface', '#ffffff'),
    brand: cssVar('--color-brand', '#1d4ed8'),
    fit: cssVar('--color-critical-solid', '#dc2626'),
    series: [cssVar('--color-cat-1', '#2563eb'), cssVar('--color-cat-4', '#c2410c')],
    groups: ['--color-cat-1', '--color-cat-2', '--color-cat-3', '--color-cat-4', '--color-cat-5'].map((v) =>
      cssVar(v, '#2563eb'),
    ),
    other: cssVar('--color-nodata-solid', '#64748b'),
  }
}

/** "Vertical 1 · Setpoint": zone names only, no parameter IDs (ADR-0009). The api builds it. */
export function variableLabel(v: AnalyticsVariable): string {
  return v.label
}

/** "very weak/none" → "Very weak/none". */
export function sentenceCase(s: string | null | undefined): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : '—'
}

export function axisName(v: AnalyticsVariable): string {
  return v.unit ? `${variableLabel(v)} (${v.unit})` : variableLabel(v)
}

/** Enough digits for the magnitude: 185.1, 1.29, 0.013. */
export function formatValue(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const size = Math.abs(value)
  const digits = size >= 100 ? 1 : size >= 1 ? 2 : 3
  return value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function withUnit(value: number, v: AnalyticsVariable): string {
  return v.unit ? `${formatValue(value)} ${v.unit}` : formatValue(value)
}

function baseAxis(p: Palette) {
  return {
    axisLine: { lineStyle: { color: p.line } },
    axisTick: { lineStyle: { color: p.line } },
    axisLabel: { color: p.inkSoft, fontSize: 11 },
    splitLine: { lineStyle: { color: p.lineSoft } },
    nameTextStyle: { color: p.inkSoft, fontSize: 12, fontWeight: 600 },
  }
}

const tooltipBase = (p: Palette) => ({
  backgroundColor: p.surface,
  borderColor: p.line,
  textStyle: { color: p.ink, fontSize: 12 },
  extraCssText: 'box-shadow: 0 8px 24px rgb(15 23 42 / 0.12);',
})

const toolbox = (p: Palette) => ({
  right: 8,
  top: 0,
  itemSize: 14,
  iconStyle: { borderColor: p.inkSoft },
  feature: {
    dataZoom: { title: { zoom: 'Zoom to area', back: 'Undo zoom' } },
    restore: { title: 'Reset zoom' },
  },
})

type Point = [number, number, number] // x, y, bucket start

export function scatterOption(result: AnalyticsResult, p: Palette): EChartsCoreOption {
  const pairs = result.pairs
  if (!pairs) return {}
  const points: Point[] = pairs.x.map((x, i) => [x, pairs.y[i] ?? Number.NaN, pairs.t[i] ?? 0])
  const visible = result.groups?.items.map((g) => g.key) ?? []
  const series: object[] = []

  const scatter = (name: string, data: Point[], color: string) => ({
    type: 'scatter',
    name,
    data,
    symbolSize: 5,
    large: data.length > 3000,
    itemStyle: { color, opacity: 0.6 },
    emphasis: { itemStyle: { opacity: 1, borderColor: p.ink, borderWidth: 1 } },
  })

  if (pairs.g && result.groups) {
    const labels = new Map(result.groups.items.map((g) => [g.key, g.label]))
    visible.forEach((key, i) => {
      const data = points.filter((_, j) => pairs.g?.[j] === key)
      series.push(scatter(labels.get(key) ?? key, data, p.groups[i % p.groups.length] ?? p.brand))
    })
    const rest = points.filter((_, j) => !visible.includes(pairs.g?.[j] ?? ''))
    if (rest.length) series.push(scatter('Other groups', rest, p.other))
  } else {
    series.push(scatter('Paired buckets', points, p.brand))
  }

  const corr = result.statistics?.correlation
  if (corr?.computable && corr.slope !== null && corr.intercept !== null && pairs.x.length) {
    const lo = Math.min(...pairs.x)
    const hi = Math.max(...pairs.x)
    series.push({
      type: 'line',
      name: 'Least-squares fit',
      data: [
        [lo, corr.intercept + corr.slope * lo],
        [hi, corr.intercept + corr.slope * hi],
      ],
      showSymbol: false,
      silent: true,
      lineStyle: { color: p.fit, width: 2, type: 'dashed' },
      itemStyle: { color: p.fit },
      tooltip: { show: false },
      z: 5,
    })
  }

  return {
    animation: false,
    aria: { enabled: true },
    grid: { left: 72, right: 28, top: 44, bottom: 60 },
    legend: { top: 0, left: 0, textStyle: { color: p.inkSoft, fontSize: 12 }, icon: 'circle' },
    toolbox: toolbox(p),
    tooltip: {
      trigger: 'item',
      ...tooltipBase(p),
      formatter: (item: { data?: unknown; seriesName?: string }) => {
        const [x, y, t] = (item.data ?? []) as Point
        return [
          `<b>${formatManilaFull(t)}</b> <span style="color:${p.inkMuted}">Manila</span>`,
          `X ${variableLabel(result.x)}: <b>${withUnit(x, result.x)}</b>`,
          `Y ${variableLabel(result.y)}: <b>${withUnit(y, result.y)}</b>`,
          pairs.g ? `Group: ${item.seriesName ?? ''}` : '',
        ]
          .filter(Boolean)
          .join('<br/>')
      },
    },
    xAxis: { type: 'value', name: axisName(result.x), nameLocation: 'middle', nameGap: 34, scale: true, ...baseAxis(p) },
    yAxis: { type: 'value', name: axisName(result.y), nameLocation: 'middle', nameGap: 52, scale: true, ...baseAxis(p) },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
      { type: 'inside', yAxisIndex: 0, filterMode: 'none' },
    ],
    series,
  }
}

/** Breaks the line wherever buckets are missing (ANA-15: gaps for missing values). */
function withGaps(t: number[], v: number[], stepMs: number): (number | null)[][] {
  const out: (number | null)[][] = []
  for (let i = 0; i < t.length; i++) {
    const ti = t[i] ?? 0
    const prev = t[i - 1]
    if (prev !== undefined && ti - prev > stepMs) out.push([prev + stepMs, null])
    out.push([ti, v[i] ?? null])
  }
  return out
}

export function trendOption(result: AnalyticsResult, p: Palette): EChartsCoreOption {
  const pairs = result.pairs
  if (!pairs) return {}
  const step = result.query.bucketSeconds * 1000
  const sameUnit = result.x.unit === result.y.unit
  // A setpoint is drawn dashed and on top, so it stays visible where the actual tracks it.
  const line = (v: AnalyticsVariable, data: (number | null)[][], color: string, axis: number) => ({
    type: 'line',
    name: `${v === result.x ? 'X' : 'Y'} ${variableLabel(v)}`,
    data,
    yAxisIndex: axis,
    showSymbol: false,
    connectNulls: false,
    z: v.kind === 'setpoint' ? 3 : 2,
    lineStyle: { color, width: v.kind === 'setpoint' ? 1.8 : 1.6, type: v.kind === 'setpoint' ? 'dashed' : 'solid' },
    itemStyle: { color },
  })
  const axis = (v: AnalyticsVariable | null, position: 'left' | 'right', color?: string) => ({
    type: 'value',
    scale: true,
    position,
    name: v ? (v.unit ?? 'no unit') : (result.x.unit ?? ''),
    nameTextStyle: { color: color ?? p.inkSoft, fontSize: 12, fontWeight: 600 },
    axisLine: { show: !sameUnit, lineStyle: { color: color ?? p.line } },
    axisLabel: { color: color ?? p.inkSoft, fontSize: 11 },
    splitLine: { show: position === 'left', lineStyle: { color: p.lineSoft } },
  })

  return {
    animation: false,
    aria: { enabled: true },
    grid: { left: 64, right: sameUnit ? 28 : 64, top: 64, bottom: 84 },
    legend: { top: 0, left: 0, textStyle: { color: p.inkSoft, fontSize: 12 } },
    toolbox: toolbox(p),
    tooltip: {
      trigger: 'axis',
      ...tooltipBase(p),
      axisPointer: { type: 'line', lineStyle: { color: p.inkMuted } },
      formatter: (items: { data?: unknown; seriesIndex?: number }[]) => {
        const first = items[0]?.data as [number, number | null] | undefined
        if (!first) return ''
        const rows = items.map((it) => {
          const [, value] = it.data as [number, number | null]
          const v = it.seriesIndex === 0 ? result.x : result.y
          return `${it.seriesIndex === 0 ? 'X' : 'Y'} ${variableLabel(v)}: <b>${value === null ? 'missing' : withUnit(value, v)}</b>`
        })
        return [`<b>${formatManilaFull(first[0])}</b> <span style="color:${p.inkMuted}">Manila</span>`, ...rows].join('<br/>')
      },
    },
    xAxis: {
      type: 'time',
      ...baseAxis(p),
      splitLine: { show: false },
      axisLabel: { color: p.inkSoft, fontSize: 11, formatter: (value: number) => formatManilaShort(value), hideOverlap: true },
    },
    yAxis: sameUnit
      ? [axis(null, 'left')]
      : [axis(result.x, 'left', p.series[0]), axis(result.y, 'right', p.series[1])],
    dataZoom: [
      { type: 'inside', xAxisIndex: 0 },
      {
        type: 'slider',
        xAxisIndex: 0,
        height: 22,
        bottom: 18,
        borderColor: p.line,
        textStyle: { color: p.inkSoft, fontSize: 11 },
        labelFormatter: (value: number) => formatManilaShort(value),
      },
    ],
    series: [
      line(result.x, withGaps(pairs.t, pairs.x, step), p.series[0], 0),
      line(result.y, withGaps(pairs.t, pairs.y, step), p.series[1], sameUnit ? 0 : 1),
    ],
  }
}
