import { AlertOctagon, AlertTriangle, Gauge, SlidersHorizontal } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { MaintenanceBar, SwitchOffDialog, SwitchedOffCard } from '@/components/live/ControlParts'
import { EventSheet } from '@/components/live/EventSheet'
import { MonitorBanner } from '@/components/live/MonitorBanner'
import { OpenEvents } from '@/components/live/OpenEvents'
import { RecentActivity } from '@/components/live/RecentActivity'
import { ZoneTable } from '@/components/live/ZoneTable'
import { CardGridSkeleton, TableSkeleton } from '@/components/shared/LoadingSkeleton'
import { PageHeader } from '@/components/shared/PageHeader'
import { SummaryCard } from '@/components/shared/SummaryCard'
import { useRoles } from '@/hooks/useAuth'
import { useLiveCenterline } from '@/hooks/useLiveCenterline'
import { monitoringApi } from '@/services/monitoringApi'
import type { LiveParameter, LiveZone } from '@/types/monitoringApi'
import { formatManilaFull } from '@/utils/manilaTime'

/**
 * Digital Centerline, live (ADR-0015): every monitored zone's target, HMI setpoint and
 * actual, and the states monitor-core has judged. Nothing is judged in the browser.
 */
export function LiveCenterlinePage() {
  const { view, error, updatedAt } = useLiveCenterline()
  const [openId, setOpenId] = useState<string | null>(null)
  const [switching, setSwitching] = useState<{ zone: LiveZone; parameter: LiveParameter } | null>(null)
  const [clock, setClock] = useState(() => Date.now())
  const { isManager, isAdministrator } = useRoles()

  useEffect(() => {
    const t = window.setInterval(() => setClock(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [])

  // Count down on the server's clock: the skew measured at the last refresh
  const skew = view && updatedAt ? Date.parse(view.serverTime) - updatedAt : 0
  const now = clock + skew
  const counts = view?.counts

  const allZones = view?.parameters.flatMap((p) => p.zones) ?? []
  const targets = view ? { set: allZones.filter((z) => z.target != null).length, zones: allZones.length } : undefined

  // A Manager switches a zone off with a reason (a dialog), or on again at once (MON-01)
  const onSwitch = (zone: LiveZone, parameter: LiveParameter, on: boolean) => {
    if (!on) return setSwitching({ zone, parameter })
    monitoringApi
      .switchZones([zone.channel], true, '')
      .then(() => toast.success(`Monitoring switched on for ${zone.name}`, { description: "It's judged again on its next fresh values." }))
      .catch((caught: unknown) => toast.error(caught instanceof Error ? caught.message : String(caught)))
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Digital Centerline"
        description="Target, HMI setpoint and actual for every monitored zone, as monitor-core judges them."
        breadcrumbs={[{ label: 'Monitoring' }, { label: 'Digital Centerline' }]}
        actions={
          updatedAt ? (
            <span className="text-ink-muted text-[12px]">Updated {formatManilaFull(updatedAt)} Manila</span>
          ) : undefined
        }
      />

      <MonitorBanner monitor={view?.monitor} error={error} targets={targets} />
      {view && <MaintenanceBar windows={view.control.maintenance} now={now} canManage={isAdministrator} />}

      {!view ? (
        <>
          <CardGridSkeleton count={4} />
          <TableSkeleton rows={12} />
        </>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
            <SummaryCard label="Zones monitored" value={counts!.zones} supportingText="From the register in effect" icon={Gauge} tone="brand" />
            <SummaryCard label="HMI mismatches" value={counts!.hmiOpen} supportingText="Setpoint off target past the delay"
                         icon={SlidersHorizontal} tone={counts!.hmiOpen ? 'warning' : 'neutral'} />
            <SummaryCard label="Warnings" value={counts!.warning} supportingText="Actual past the Warning limits"
                         icon={AlertTriangle} tone={counts!.warning ? 'warning' : 'neutral'} />
            <SummaryCard label="Criticals" value={counts!.critical} supportingText="Actual past the Critical limits"
                         icon={AlertOctagon} tone={counts!.critical ? 'critical' : 'neutral'} />
          </div>

          <SwitchedOffCard zones={view.control.switchedOff} canSwitch={isManager} onChanged={() => undefined} />

          <div className="grid grid-cols-1 items-start gap-4 2xl:grid-cols-[minmax(0,5fr)_minmax(0,2fr)]">
            <ZoneTable parameters={view.parameters} now={now} onOpenEvent={setOpenId} onSwitch={isManager ? onSwitch : undefined} />
            <OpenEvents events={view.events} now={now} onOpen={setOpenId} />
          </div>

          <RecentActivity onOpen={setOpenId} />
        </>
      )}

      {openId && <EventSheet key={openId} id={openId} onClose={() => setOpenId(null)} onOpen={setOpenId} />}
      {switching && (
        <SwitchOffDialog zone={switching.zone} parameter={switching.parameter} onClose={() => setSwitching(null)}
                         onDone={() => setSwitching(null)} />
      )}
    </div>
  )
}
