import type { AlarmSeverity, AlarmStatus } from '@/types'
import { cn } from '@/utils/cn'
import { ALARM_STATUS_META, SEVERITY_META } from '@/utils/status'

export function AlarmSeverityBadge({
  severity,
  className,
}: {
  severity: AlarmSeverity
  className?: string
}) {
  const meta = SEVERITY_META[severity]
  const Icon = meta.icon

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[12px] font-medium whitespace-nowrap',
        meta.badge,
        className,
      )}
    >
      <Icon className="size-3.5 shrink-0" aria-hidden />
      {meta.label}
    </span>
  )
}

export function AlarmStatusBadge({
  status,
  className,
}: {
  status: AlarmStatus
  className?: string
}) {
  const meta = ALARM_STATUS_META[status]

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[12px] font-medium whitespace-nowrap',
        meta.badge,
        className,
      )}
    >
      <span
        className={cn(
          'size-2 shrink-0 rounded-full',
          status === 'active'
            ? 'bg-critical-solid'
            : status === 'acknowledged'
              ? 'bg-warning-solid'
              : 'bg-normal-solid',
        )}
        aria-hidden
      />
      {meta.label}
    </span>
  )
}
