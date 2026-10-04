import {
  ChevronDown,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  X,
} from 'lucide-react'
import { useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import type { UseAnalyticsSelectionResult } from '@/hooks/useAnalyticsSelection'
import {
  CATEGORY_LABELS,
  PARAMETER_CATEGORIES,
  type ParameterCategory,
  type ParameterCode,
  type ParameterDefinition,
} from '@/types'
import { cn } from '@/utils/cn'

interface AnalyticsParameterPanelProps {
  parameters: readonly ParameterDefinition[]
  analytics: UseAnalyticsSelectionResult
  collapsed: boolean
  onToggleCollapsed: () => void
}

export function AnalyticsParameterPanel({
  parameters,
  analytics,
  collapsed,
  onToggleCollapsed,
}: AnalyticsParameterPanelProps) {
  const [search, setSearch] = useState('')
  const [closedCategories, setClosedCategories] = useState<ReadonlySet<ParameterCategory>>(
    new Set(),
  )

  const grouped = useMemo(() => {
    const term = search.trim().toLowerCase()
    const matches = parameters.filter(
      (parameter) =>
        term === '' ||
        parameter.name.toLowerCase().includes(term) ||
        CATEGORY_LABELS[parameter.category].toLowerCase().includes(term) ||
        parameter.unit.toLowerCase().includes(term),
    )

    return PARAMETER_CATEGORIES.map((category) => ({
      category,
      items: matches.filter((parameter) => parameter.category === category),
    })).filter((group) => group.items.length > 0)
  }, [parameters, search])

  if (collapsed) {
    return (
      <div className="bg-surface border-line shadow-card flex w-11 shrink-0 flex-col items-center gap-3 rounded-lg border py-3">
        <button
          type="button"
          onClick={onToggleCollapsed}
          className="text-ink-soft hover:bg-surface-muted hover:text-ink focus-visible:ring-brand-ring grid size-8 place-items-center rounded-md transition-colors focus-visible:ring-2 focus-visible:outline-none"
          aria-label="Expand parameter panel"
        >
          <PanelLeftOpen className="size-4" aria-hidden />
        </button>
        <span
          className="text-ink-muted text-[11px] font-semibold tracking-[0.08em] whitespace-nowrap uppercase"
          style={{ writingMode: 'vertical-rl' }}
        >
          Parameters
        </span>
      </div>
    )
  }

  return (
    <div className="bg-surface border-line shadow-card flex w-full shrink-0 flex-col overflow-hidden rounded-lg border xl:w-[288px]">
      <div className="border-line flex items-center justify-between gap-2 border-b px-3 py-2.5">
        <h2 className="text-ink text-[13px] font-semibold">Parameters</h2>
        <button
          type="button"
          onClick={onToggleCollapsed}
          className="text-ink-soft hover:bg-surface-muted hover:text-ink focus-visible:ring-brand-ring hidden size-7 place-items-center rounded-md transition-colors focus-visible:ring-2 focus-visible:outline-none xl:grid"
          aria-label="Collapse parameter panel"
        >
          <PanelLeftClose className="size-4" aria-hidden />
        </button>
      </div>

      {/* Axis assignment summary */}
      <div className="border-line bg-surface-muted space-y-1.5 border-b px-3 py-2.5">
        <AxisChip axis="X" code={analytics.selection.xAxis} parameters={parameters} />
        <AxisChip axis="Y" code={analytics.selection.yAxis} parameters={parameters} />
      </div>

      <div className="border-line border-b p-3">
        <div className="relative">
          <Search
            className="text-ink-muted pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
            aria-hidden
          />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search parameters…"
            aria-label="Search parameters"
            className="h-8 pr-8 pl-9 text-[13px]"
          />
          {search !== '' && (
            <button
              type="button"
              onClick={() => setSearch('')}
              className="text-ink-muted hover:text-ink absolute top-1/2 right-2 grid size-5 -translate-y-1/2 place-items-center rounded"
              aria-label="Clear parameter search"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          )}
        </div>
      </div>

      <div className="max-h-[420px] min-h-0 flex-1 overflow-y-auto p-2 xl:max-h-none">
        {grouped.length === 0 ? (
          <p className="text-ink-muted px-2 py-6 text-center text-[12px]">
            No parameter matches “{search}”.
          </p>
        ) : (
          grouped.map(({ category, items }) => (
            <Collapsible
              key={category}
              open={!closedCategories.has(category)}
              onOpenChange={(open) =>
                setClosedCategories((current) => {
                  const next = new Set(current)
                  if (open) next.delete(category)
                  else next.add(category)
                  return next
                })
              }
            >
              <CollapsibleTrigger className="text-ink-soft hover:bg-surface-muted focus-visible:ring-brand-ring group flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none">
                <span className="text-[11px] font-semibold tracking-[0.06em] uppercase">
                  {CATEGORY_LABELS[category]}
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="text-ink-muted tnum text-[11px]">{items.length}</span>
                  <ChevronDown
                    className="size-3.5 shrink-0 transition-transform group-data-[state=closed]:-rotate-90"
                    aria-hidden
                  />
                </span>
              </CollapsibleTrigger>

              <CollapsibleContent className="overflow-hidden pb-1">
                <ul className="space-y-0.5 pt-0.5">
                  {items.map((parameter) => (
                    <li key={parameter.id}>
                      <ParameterListItem parameter={parameter} analytics={analytics} />
                    </li>
                  ))}
                </ul>
              </CollapsibleContent>
            </Collapsible>
          ))
        )}
      </div>

      <div className="border-line border-t p-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={analytics.clearSelection}
          className="w-full"
        >
          Clear all selections
        </Button>
      </div>
    </div>
  )
}

function ParameterListItem({
  parameter,
  analytics,
}: {
  parameter: ParameterDefinition
  analytics: UseAnalyticsSelectionResult
}) {
  const isX = analytics.selection.xAxis === parameter.code
  const isY = analytics.selection.yAxis === parameter.code
  const selected = analytics.selection.selected.has(parameter.code)

  return (
    <div
      className={cn(
        'group flex items-center gap-1 rounded-md px-2 py-1.5 transition-colors',
        selected ? 'bg-brand-surface' : 'hover:bg-surface-muted',
      )}
    >
      <button
        type="button"
        onClick={() => analytics.toggleParameter(parameter.code)}
        className="focus-visible:ring-brand-ring min-w-0 flex-1 rounded text-left focus-visible:ring-2 focus-visible:outline-none"
      >
        <span
          className={cn(
            'block truncate text-[13px]',
            selected ? 'text-brand font-medium' : 'text-ink',
          )}
        >
          {parameter.name}
        </span>
        <span className="text-ink-muted block text-[11px]">{parameter.unit}</span>
      </button>

      <div className="flex shrink-0 gap-1">
        <AxisButton
          label="X"
          active={isX}
          onClick={() => analytics.setXAxis(parameter.code)}
          title={`Assign ${parameter.name} to the X axis`}
        />
        <AxisButton
          label="Y"
          active={isY}
          onClick={() => analytics.setYAxis(parameter.code)}
          title={`Assign ${parameter.name} to the Y axis`}
        />
      </div>
    </div>
  )
}

function AxisButton({
  label,
  active,
  onClick,
  title,
}: {
  label: string
  active: boolean
  onClick: () => void
  title: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      aria-pressed={active}
      className={cn(
        'focus-visible:ring-brand-ring grid size-6 place-items-center rounded border text-[11px] font-semibold transition-colors focus-visible:ring-2 focus-visible:outline-none',
        active
          ? 'border-brand bg-brand text-white'
          : 'border-line bg-surface text-ink-muted hover:border-brand-ring hover:text-brand',
      )}
    >
      {label}
    </button>
  )
}

function AxisChip({
  axis,
  code,
  parameters,
}: {
  axis: 'X' | 'Y'
  code: ParameterCode
  parameters: readonly ParameterDefinition[]
}) {
  const parameter = parameters.find((p) => p.code === code)

  return (
    <div className="flex items-center gap-2">
      <span className="bg-brand grid size-5 shrink-0 place-items-center rounded text-[10px] font-semibold text-white">
        {axis}
      </span>
      <span className="text-ink min-w-0 flex-1 truncate text-[12px] font-medium">
        {parameter?.name ?? '—'}
      </span>
      <span className="text-ink-muted shrink-0 text-[11px]">{parameter?.unit}</span>
    </div>
  )
}
