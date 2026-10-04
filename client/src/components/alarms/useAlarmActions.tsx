import { CheckCheck, ShieldCheck } from 'lucide-react'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'

import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { useCenterline } from '@/hooks/useCenterline'
import type { AlarmRow } from '@/types'

type PendingAction = { alarm: AlarmRow; action: 'acknowledge' | 'resolve' } | null

export interface AlarmActions {
  requestAcknowledge: (alarm: AlarmRow) => void
  requestResolve: (alarm: AlarmRow) => void
  pending: PendingAction
  cancel: () => void
  confirm: () => void
}

/**
 * Acknowledge and resolve, both gated behind a confirmation and followed by a
 * toast. Shared by the alarm panel on the Digital Centerline page and by the
 * Active Alarms and Alarm History pages so the interaction is identical
 * wherever an alarm appears.
 */
export function useAlarmActions(): AlarmActions {
  const { acknowledgeAlarm, resolveAlarm } = useCenterline()
  const [pending, setPending] = useState<PendingAction>(null)

  const requestAcknowledge = useCallback(
    (alarm: AlarmRow) => setPending({ alarm, action: 'acknowledge' }),
    [],
  )

  const requestResolve = useCallback(
    (alarm: AlarmRow) => setPending({ alarm, action: 'resolve' }),
    [],
  )

  const cancel = useCallback(() => setPending(null), [])

  const confirm = useCallback(() => {
    if (!pending) return
    const { alarm, action } = pending

    if (action === 'acknowledge') {
      acknowledgeAlarm(alarm.id)
      toast.success('Alarm acknowledged', {
        description: `${alarm.reference} — ${alarm.parameterName} on ${alarm.machineName}.`,
      })
    } else {
      resolveAlarm(alarm.id, 'Resolved from the alarm panel during this session.')
      toast.success('Alarm resolved', {
        description: `${alarm.reference} — ${alarm.parameterName} on ${alarm.machineName}.`,
      })
    }

    setPending(null)
  }, [pending, acknowledgeAlarm, resolveAlarm])

  return { requestAcknowledge, requestResolve, pending, cancel, confirm }
}

export function AlarmActionDialog({ actions }: { actions: AlarmActions }) {
  const { pending, cancel, confirm } = actions
  const acknowledging = pending?.action === 'acknowledge'

  return (
    <ConfirmDialog
      open={pending !== null}
      onOpenChange={(open) => {
        if (!open) cancel()
      }}
      icon={acknowledging ? CheckCheck : ShieldCheck}
      title={acknowledging ? 'Acknowledge this alarm?' : 'Resolve this alarm?'}
      description={
        pending
          ? acknowledging
            ? `${pending.alarm.reference} — ${pending.alarm.parameterName} on ${pending.alarm.machineName}. Acknowledging records that the deviation has been seen; it stays open until resolved.`
            : `${pending.alarm.reference} — ${pending.alarm.parameterName} on ${pending.alarm.machineName}. Resolving closes the alarm and removes it from the active list.`
          : ''
      }
      confirmLabel={acknowledging ? 'Acknowledge' : 'Resolve'}
      onConfirm={confirm}
    />
  )
}
