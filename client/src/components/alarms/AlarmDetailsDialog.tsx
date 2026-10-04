import { CheckCheck, ShieldCheck } from 'lucide-react'

import { AlarmSeverityBadge, AlarmStatusBadge } from '@/components/alarms/AlarmBadges'
import { KeyValueRow } from '@/components/shared/SectionCard'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { AlarmRow } from '@/types'
import { cn } from '@/utils/cn'
import {
  NO_VALUE,
  formatDeviation,
  formatDeviationPct,
  formatNumber,
  formatTimestamp,
} from '@/utils/format'

interface AlarmDetailsDialogProps {
  alarm: AlarmRow | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onAcknowledge: (alarm: AlarmRow) => void
  onResolve: (alarm: AlarmRow) => void
}

export function AlarmDetailsDialog({
  alarm,
  open,
  onOpenChange,
  onAcknowledge,
  onResolve,
}: AlarmDetailsDialogProps) {
  if (!alarm) return null

  const drift = alarm.hmiValue !== alarm.targetValue

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{alarm.parameterName}</DialogTitle>
          <DialogDescription>
            {alarm.reference} · {alarm.machineName} · {alarm.skuCode}
          </DialogDescription>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <AlarmSeverityBadge severity={alarm.severity} />
            <AlarmStatusBadge status={alarm.status} />
          </div>
        </DialogHeader>

        <DialogBody className="space-y-4">
          <p className="text-ink border-line bg-surface-muted rounded-md border px-3 py-2.5 text-[13px] leading-relaxed">
            {alarm.message}
          </p>

          {drift && (
            <p className="border-warning-border bg-warning-surface text-warning rounded-md border px-3 py-2.5 text-[12px] leading-relaxed">
              <strong className="font-semibold">Setpoint drift detected.</strong> The HMI
              panel value ({formatNumber(alarm.hmiValue, alarm.parameterDecimals)}{' '}
              {alarm.unit}) does not match the centerline target (
              {formatNumber(alarm.targetValue, alarm.parameterDecimals)} {alarm.unit}).
              Reconcile the recipe before adjusting the process.
            </p>
          )}

          <div>
            <h3 className="micro-label mb-2">Measurement</h3>
            <dl className="divide-line-soft divide-y">
              <KeyValueRow label="Target value">
                <span className="tnum">
                  {formatNumber(alarm.targetValue, alarm.parameterDecimals)} {alarm.unit}
                </span>
              </KeyValueRow>
              <KeyValueRow label="HMI value">
                <span className={cn('tnum', drift && 'text-warning')}>
                  {formatNumber(alarm.hmiValue, alarm.parameterDecimals)} {alarm.unit}
                </span>
              </KeyValueRow>
              <KeyValueRow label="Actual value">
                <span className="tnum font-semibold">
                  {alarm.actualValue === null
                    ? NO_VALUE
                    : `${formatNumber(alarm.actualValue, alarm.parameterDecimals)} ${alarm.unit}`}
                </span>
              </KeyValueRow>
              <KeyValueRow label="Deviation">
                <span className="tnum">
                  {formatDeviation(alarm.deviation, alarm.parameterDecimals)}{' '}
                  {alarm.deviation !== null && alarm.unit}
                  {alarm.deviationPct !== null && (
                    <span className="text-ink-muted ml-1.5 font-normal">
                      ({formatDeviationPct(alarm.deviationPct)})
                    </span>
                  )}
                </span>
              </KeyValueRow>
            </dl>
          </div>

          <div>
            <h3 className="micro-label mb-2">Context</h3>
            <dl className="divide-line-soft divide-y">
              <KeyValueRow label="Factory">{alarm.factoryName}</KeyValueRow>
              <KeyValueRow label="Production line">{alarm.lineName}</KeyValueRow>
              <KeyValueRow label="Machine">{alarm.machineName}</KeyValueRow>
              <KeyValueRow label="SKU">{alarm.skuCode}</KeyValueRow>
            </dl>
          </div>

          <div>
            <h3 className="micro-label mb-2">Timeline</h3>
            <dl className="divide-line-soft divide-y">
              <KeyValueRow label="Raised">
                <span className="tnum">{formatTimestamp(alarm.raisedAt)}</span>
              </KeyValueRow>
              {alarm.acknowledgedAt && (
                <KeyValueRow label="Acknowledged">
                  <span className="tnum block">{formatTimestamp(alarm.acknowledgedAt)}</span>
                  <span className="text-ink-muted block text-[11px] font-normal">
                    by {alarm.acknowledgedBy}
                  </span>
                </KeyValueRow>
              )}
              {alarm.resolvedAt && (
                <KeyValueRow label="Resolved">
                  <span className="tnum block">{formatTimestamp(alarm.resolvedAt)}</span>
                  <span className="text-ink-muted block text-[11px] font-normal">
                    by {alarm.resolvedBy}
                  </span>
                </KeyValueRow>
              )}
            </dl>
          </div>

          {alarm.resolutionNote && (
            <div>
              <h3 className="micro-label mb-2">Resolution note</h3>
              <p className="text-ink-soft border-normal-border bg-normal-surface rounded-md border px-3 py-2.5 text-[13px] leading-relaxed">
                {alarm.resolutionNote}
              </p>
            </div>
          )}
        </DialogBody>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          {alarm.status === 'active' && (
            <Button onClick={() => onAcknowledge(alarm)} className="gap-1.5">
              <CheckCheck className="size-4" aria-hidden />
              Acknowledge
            </Button>
          )}
          {alarm.status !== 'resolved' && (
            <Button
              variant="outline"
              onClick={() => onResolve(alarm)}
              className="border-normal-border text-normal hover:bg-normal-surface gap-1.5"
            >
              <ShieldCheck className="size-4" aria-hidden />
              Resolve
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
