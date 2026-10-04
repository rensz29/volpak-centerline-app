import { CalendarClock, History, Plus, Wrench } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'

import { windowScope, windowTiming, windowTone } from '@/components/live/controlModel'
import { TONE } from '@/components/live/liveModel'
import { OpenWindowDialog, WindowActionDialog } from '@/components/maintenance/WindowDialogs'
import { EmptyState } from '@/components/shared/EmptyState'
import { TableSkeleton } from '@/components/shared/LoadingSkeleton'
import { PageHeader } from '@/components/shared/PageHeader'
import { SectionCard } from '@/components/shared/SectionCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useRoles } from '@/hooks/useAuth'
import { monitoringApi } from '@/services/monitoringApi'
import type { LiveParameter, MaintenanceWindow } from '@/types/monitoringApi'
import { cn } from '@/utils/cn'

const EVERY_MS = 20_000
const STATUS_LABEL: Record<MaintenanceWindow['status'], string> = {
  scheduled: 'Scheduled', active: 'In force', overdue: 'Overdue', ended: 'Ended', cancelled: 'Cancelled',
}

/** Maintenance windows (MNT-01, ADR-0017): Managers see them, Administrators open, extend and end them. */
export function MaintenancePage() {
  const { isAdministrator } = useRoles()
  const [windows, setWindows] = useState<MaintenanceWindow[] | null>(null)
  const [serverNow, setServerNow] = useState(0)
  const [parameters, setParameters] = useState<LiveParameter[]>([])
  const [error, setError] = useState<string | null>(null)
  const [opening, setOpening] = useState(false)
  const [acting, setActing] = useState<{ window: MaintenanceWindow; action: 'extend' | 'end' } | null>(null)

  const load = useCallback(() => {
    monitoringApi
      .maintenance()
      .then((r) => {
        setWindows(r.windows)
        setServerNow(Date.parse(r.serverTime))
      })
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : String(caught)))
  }, [])

  useEffect(() => {
    load()
    const t = window.setInterval(load, EVERY_MS)
    monitoringApi
      .live()
      .then((v) => setParameters(v.parameters))
      .catch(() => undefined)
    return () => window.clearInterval(t)
  }, [load])

  const current = (windows ?? []).filter((w) => w.status === 'active' || w.status === 'overdue' || w.status === 'scheduled')
  const past = (windows ?? []).filter((w) => w.status === 'ended' || w.status === 'cancelled')

  const row = (w: MaintenanceWindow, actions: boolean) => (
    <tr key={w.id} className="border-line-soft border-b last:border-b-0">
      <td className="px-5 py-2">
        <Badge variant={w.status === 'overdue' ? 'critical' : w.status === 'active' ? 'warning' : 'outline'}>{STATUS_LABEL[w.status]}</Badge>
      </td>
      <td className="text-ink px-3 py-2">
        <span className="font-medium">{w.scope === 'line' ? 'Whole line' : windowScope(w)}</span>
        <span className="text-ink-soft block text-[12px]">“{w.reason}” · by {w.createdBy}</span>
      </td>
      <td className={cn('px-3 py-2 text-[12px]', actions ? TONE[windowTone(w, serverNow)].text : 'text-ink-soft')}>{windowTiming(w, serverNow)}</td>
      <td className="px-3 py-2 text-right whitespace-nowrap">
        {actions && isAdministrator && (
          <>
            {w.status !== 'scheduled' && (
              <Button type="button" variant="ghost" size="sm" onClick={() => setActing({ window: w, action: 'extend' })}>
                <CalendarClock className="size-3.5" aria-hidden /> Move end
              </Button>
            )}
            <Button type="button" variant="outline" size="sm" onClick={() => setActing({ window: w, action: 'end' })}>
              {w.status === 'scheduled' ? 'Cancel' : 'End now'}
            </Button>
          </>
        )}
      </td>
    </tr>
  )

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Maintenance"
        description="Windows when nothing is judged on the whole line or on chosen zones (MNT-01). The page warns 30 and 5 min before a window's planned end; past it, the window stays in force, overdue, until it's ended."
        breadcrumbs={[{ label: 'Setup' }, { label: 'Maintenance' }]}
        actions={
          isAdministrator ? (
            <Button type="button" size="sm" onClick={() => setOpening(true)}>
              <Plus className="size-4" aria-hidden /> Open a window
            </Button>
          ) : undefined
        }
      />

      {error ? (
        <div className="bg-surface border-line shadow-card rounded-lg border">
          <EmptyState icon={Wrench} title="Can't load the maintenance windows" description={error} />
        </div>
      ) : !windows ? (
        <TableSkeleton rows={3} />
      ) : (
        <>
          <SectionCard title="In force and coming" icon={Wrench} flush
                       description={current.length ? `${current.length} window${current.length === 1 ? '' : 's'}` : 'None: everything is judged'}>
            {current.length > 0 && (
              <table className="w-full text-[13px]">
                <tbody>{current.map((w) => row(w, true))}</tbody>
              </table>
            )}
          </SectionCard>
          <SectionCard title="History" description="Ended and cancelled windows, newest first" icon={History} flush>
            {past.length === 0 ? (
              <p className="text-ink-soft px-5 py-4 text-[13px]">None yet.</p>
            ) : (
              <table className="w-full text-[13px]">
                <tbody>{past.map((w) => row(w, false))}</tbody>
              </table>
            )}
          </SectionCard>
        </>
      )}

      {opening && (
        <OpenWindowDialog
          parameters={parameters}
          onClose={() => setOpening(false)}
          onDone={(w) => {
            setOpening(false)
            toast.success(w.status === 'scheduled' ? 'Maintenance scheduled' : 'Maintenance started', {
              description: `${windowScope(w)} ${w.status === 'scheduled' ? 'will stop being' : 'is no longer'} judged; monitor-core applies it within 2 s.`,
            })
            load()
          }}
        />
      )}
      {acting && (
        <WindowActionDialog
          window={acting.window}
          action={acting.action}
          onClose={() => setActing(null)}
          onDone={() => {
            setActing(null)
            load()
          }}
        />
      )}
    </div>
  )
}
