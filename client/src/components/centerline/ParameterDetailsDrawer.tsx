import { useMemo } from 'react'
import { Settings2 } from 'lucide-react'

import { ParameterTrendChart } from '@/components/centerline/ParameterTrendChart'
import { SetpointHistoryTimeline } from '@/components/centerline/SetpointHistoryTimeline'
import { ThreeValueStrip } from '@/components/centerline/ThreeValueStrip'
import { KeyValueRow } from '@/components/shared/SectionCard'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { useCenterline } from '@/hooks/useCenterline'
import { CATEGORY_LABELS, type CenterlineRow } from '@/types'
import { cn } from '@/utils/cn'
import {
  formatDeviation,
  formatDeviationPct,
  formatNumber,
  formatRelativeTime,
  formatTimestamp,
} from '@/utils/format'
import { buildTrend } from '@/utils/selectors'
import { STATUS_META } from '@/utils/status'

interface ParameterDetailsDrawerProps {
  row: CenterlineRow | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onEditConfiguration: (row: CenterlineRow) => void
}

export function ParameterDetailsDrawer({
  row,
  open,
  onOpenChange,
  onEditConfiguration,
}: ParameterDetailsDrawerProps) {
  const { samples, setpointHistory } = useCenterline()

  const trend = useMemo(() => {
    if (!row) return []
    return buildTrend(
      samples,
      row.parameter.code,
      row.reading.machineId,
      row.parameter,
      row.reading,
    )
  }, [samples, row])

  const history = useMemo(() => {
    if (!row) return []
    return setpointHistory
      .filter(
        (change) =>
          change.parameterId === row.parameter.id &&
          change.machineId === row.reading.machineId,
      )
      .sort((a, b) => b.changedAt.localeCompare(a.changedAt))
  }, [setpointHistory, row])

  if (!row) return null

  const meta = STATUS_META[row.status]

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-[600px]">
        <SheetHeader>
          <div className="flex items-start gap-3">
            <span className={cn('mt-1 h-10 w-1 shrink-0 rounded-full', meta.rail)} aria-hidden />
            <div className="min-w-0">
              <SheetTitle>{row.parameter.name}</SheetTitle>
              <SheetDescription>
                {row.machineName} · {row.lineName} · {row.skuCode}
              </SheetDescription>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <StatusBadge status={row.status} />
                <span className="border-line bg-surface-muted text-ink-soft rounded-md border px-2 py-0.5 text-[12px]">
                  {CATEGORY_LABELS[row.parameter.category]}
                </span>
              </div>
            </div>
          </div>
        </SheetHeader>

        <SheetBody className="divide-line divide-y">
          <Section>
            <p className="text-ink-soft text-[13px] leading-relaxed">
              {row.parameter.description}
            </p>
          </Section>

          <Section title="Comparison">
            <ThreeValueStrip row={row} />

            <dl className="mt-3">
              <KeyValueRow label="Difference from target">
                <span
                  className={cn(
                    'tnum',
                    row.status === 'normal' ? 'text-ink' : meta.text,
                  )}
                >
                  {formatDeviation(row.deviation, row.parameter.decimals)}{' '}
                  {row.deviation !== null && row.parameter.unit}
                </span>
              </KeyValueRow>
              <KeyValueRow label="Percentage deviation">
                <span
                  className={cn(
                    'tnum',
                    row.status === 'normal' ? 'text-ink' : meta.text,
                  )}
                >
                  {formatDeviationPct(row.deviationPct)}
                </span>
              </KeyValueRow>
              <KeyValueRow label="Warning tolerance">
                <span className="tnum text-warning">
                  ±{formatNumber(row.parameter.warningTolerancePct, 1)}%
                </span>
              </KeyValueRow>
              <KeyValueRow label="Critical tolerance">
                <span className="tnum text-critical">
                  ±{formatNumber(row.parameter.criticalTolerancePct, 1)}%
                </span>
              </KeyValueRow>
              <KeyValueRow label="Allowable range">
                <span className="tnum">
                  {formatNumber(row.parameter.minAllowed, row.parameter.decimals)} –{' '}
                  {formatNumber(row.parameter.maxAllowed, row.parameter.decimals)}{' '}
                  {row.parameter.unit}
                </span>
              </KeyValueRow>
            </dl>
          </Section>

          <Section title="Context">
            <dl>
              <KeyValueRow label="Factory">{row.factoryName}</KeyValueRow>
              <KeyValueRow label="Production line">{row.lineName}</KeyValueRow>
              <KeyValueRow label="Machine">{row.machineName}</KeyValueRow>
              <KeyValueRow label="SKU">
                <span className="block">{row.skuCode}</span>
                <span className="text-ink-muted block text-[11px] font-normal">
                  {row.skuName}
                </span>
              </KeyValueRow>
              <KeyValueRow label="Last updated">
                <span className="block">{formatTimestamp(row.reading.updatedAt)}</span>
                <span className="text-ink-muted block text-[11px] font-normal">
                  {formatRelativeTime(row.reading.updatedAt)}
                </span>
              </KeyValueRow>
              <KeyValueRow label="Updated by">{row.reading.updatedBy}</KeyValueRow>
            </dl>
          </Section>

          <Section
            title="Recent trend"
            hint="Actual reading against both setpoints, with the warning tolerance band shaded."
          >
            <ParameterTrendChart
              points={trend}
              parameter={row.parameter}
              height={260}
              showBrush={false}
            />
          </Section>

          <Section
            title="Setpoint change history"
            hint="Audit trail of every recorded configuration change for this parameter."
          >
            <SetpointHistoryTimeline changes={history} />
          </Section>
        </SheetBody>

        <SheetFooter className="justify-end">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button onClick={() => onEditConfiguration(row)} className="gap-1.5">
            <Settings2 className="size-4" aria-hidden />
            Edit configuration
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

function Section({
  title,
  hint,
  children,
}: {
  title?: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <section className="px-5 py-4">
      {title && <h3 className="micro-label mb-0.5">{title}</h3>}
      {hint && <p className="text-ink-muted mb-3 text-[12px]">{hint}</p>}
      <div className={cn(title && !hint && 'mt-2.5')}>{children}</div>
    </section>
  )
}
