import { RotateCcw, SlidersHorizontal } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ALL } from '@/context/ScopeContext'
import type { GroupBy, UseAnalyticsSelectionResult } from '@/hooks/useAnalyticsSelection'
import type { ScopeContextValue } from '@/context/ScopeContext'
import {
  SHIFTS,
  type Factory,
  type Machine,
  type ProductionLine,
  type Shift,
  type Sku,
} from '@/types'
import { cn } from '@/utils/cn'

export type ChartTab = 'scatter' | 'trend'

interface AnalyticsFilterBarProps {
  analytics: UseAnalyticsSelectionResult
  scope: ScopeContextValue
  factories: readonly Factory[]
  lines: readonly ProductionLine[]
  machines: readonly Machine[]
  skus: readonly Sku[]
  chartTab: ChartTab
  onChartTabChange: (tab: ChartTab) => void
  onResetAll: () => void
}

export function AnalyticsFilterBar({
  analytics,
  scope,
  factories,
  lines,
  machines,
  skus,
  chartTab,
  onChartTabChange,
  onResetAll,
}: AnalyticsFilterBarProps) {
  const availableLines =
    scope.factoryId === ALL
      ? lines
      : lines.filter((line) => line.factoryId === scope.factoryId)

  const availableMachines = machines.filter((machine) => {
    if (scope.lineId !== ALL) return machine.lineId === scope.lineId
    if (scope.factoryId !== ALL) return machine.factoryId === scope.factoryId
    return true
  })

  const scopeActive =
    (scope.factoryId !== ALL ? 1 : 0) +
    (scope.lineId !== ALL ? 1 : 0) +
    (scope.machineId !== ALL ? 1 : 0)
  const activeCount = analytics.activeFilterCount + scopeActive

  return (
    <div className="bg-surface border-line shadow-card rounded-lg border">
      <div className="border-line flex items-center justify-between gap-3 border-b px-4 py-2.5">
        <div className="text-ink-soft flex items-center gap-2 text-[13px] font-medium">
          <SlidersHorizontal className="size-4" aria-hidden />
          Analytics filters
          {activeCount > 0 && (
            <span className="bg-brand-surface text-brand tnum rounded px-1.5 py-0.5 text-[11px] font-semibold">
              {activeCount} active
            </span>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={onResetAll}
          disabled={activeCount === 0}
          className="gap-1.5"
        >
          <RotateCcw className="size-3.5" aria-hidden />
          Reset filters
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
        <Field label="Factory">
          <Select value={scope.factoryId} onValueChange={scope.setFactory}>
            <SelectTrigger size="sm" aria-label="Factory">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All factories</SelectItem>
              {factories.map((factory) => (
                <SelectItem key={factory.id} value={factory.id}>
                  {factory.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field label="Production line">
          <Select value={scope.lineId} onValueChange={scope.setLine}>
            <SelectTrigger size="sm" aria-label="Production line">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All lines</SelectItem>
              {availableLines.map((line) => (
                <SelectItem key={line.id} value={line.id}>
                  {line.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field label="Machine">
          <Select value={scope.machineId} onValueChange={scope.setMachine}>
            <SelectTrigger size="sm" aria-label="Machine">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All machines</SelectItem>
              {availableMachines.map((machine) => (
                <SelectItem key={machine.id} value={machine.id}>
                  {machine.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field label="SKU">
          <Select value={analytics.filters.skuId} onValueChange={analytics.setSkuId}>
            <SelectTrigger size="sm" aria-label="SKU">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All SKUs</SelectItem>
              {skus.map((sku) => (
                <SelectItem key={sku.id} value={sku.id}>
                  {sku.code}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field label="Shift">
          <Select
            value={analytics.filters.shift}
            onValueChange={(value) => analytics.setShift(value as Shift | typeof ALL)}
          >
            <SelectTrigger size="sm" aria-label="Shift">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All shifts</SelectItem>
              {SHIFTS.map((shift) => (
                <SelectItem key={shift} value={shift}>
                  Shift {shift}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field label="Start date">
          <Input
            type="date"
            value={analytics.filters.startDate}
            max={analytics.filters.endDate}
            onChange={(event) => analytics.setStartDate(event.target.value)}
            aria-label="Start date"
            className="tnum h-8 text-[13px]"
          />
        </Field>

        <Field label="End date">
          <Input
            type="date"
            value={analytics.filters.endDate}
            min={analytics.filters.startDate}
            onChange={(event) => analytics.setEndDate(event.target.value)}
            aria-label="End date"
            className="tnum h-8 text-[13px]"
          />
        </Field>

        <Field label="Chart type">
          <Select
            value={chartTab}
            onValueChange={(value) => onChartTabChange(value as ChartTab)}
          >
            <SelectTrigger size="sm" aria-label="Chart type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="scatter">Scatter analysis</SelectItem>
              <SelectItem value="trend">Trend comparison</SelectItem>
            </SelectContent>
          </Select>
        </Field>
      </div>
    </div>
  )
}

export function GroupBySelect({
  value,
  onChange,
  className,
}: {
  value: GroupBy
  onChange: (value: GroupBy) => void
  className?: string
}) {
  return (
    <Select value={value} onValueChange={(next) => onChange(next as GroupBy)}>
      <SelectTrigger size="sm" aria-label="Group points by" className={cn('w-[132px]', className)}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="sku">Colour by SKU</SelectItem>
        <SelectItem value="machine">Colour by machine</SelectItem>
        <SelectItem value="shift">Colour by shift</SelectItem>
      </SelectContent>
    </Select>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <span className="micro-label mb-1.5 block">{label}</span>
      {children}
    </div>
  )
}
