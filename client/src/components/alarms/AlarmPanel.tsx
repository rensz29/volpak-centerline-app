import { BellOff, BellRing, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { AlarmCard } from '@/components/alarms/AlarmCard'
import { AlarmDetailsDialog } from '@/components/alarms/AlarmDetailsDialog'
import { AlarmActionDialog, useAlarmActions } from '@/components/alarms/useAlarmActions'
import { EmptyState } from '@/components/shared/EmptyState'
import { SectionCard } from '@/components/shared/SectionCard'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ROUTES } from '@/routes/navigation'
import type { AlarmRow } from '@/types'

type AlarmTab = 'active' | 'acknowledged' | 'all'

interface AlarmPanelProps {
  alarms: readonly AlarmRow[]
  /** Cards shown before the panel links out to the full Active Alarms page. */
  limit?: number
}

export function AlarmPanel({ alarms, limit = 4 }: AlarmPanelProps) {
  const [tab, setTab] = useState<AlarmTab>('active')
  const [detailsAlarm, setDetailsAlarm] = useState<AlarmRow | null>(null)
  const actions = useAlarmActions()

  const unresolved = useMemo(
    () =>
      alarms
        .filter((alarm) => alarm.status !== 'resolved')
        .sort((a, b) => b.raisedAt.localeCompare(a.raisedAt)),
    [alarms],
  )

  const counts = useMemo(
    () => ({
      active: unresolved.filter((alarm) => alarm.status === 'active').length,
      acknowledged: unresolved.filter((alarm) => alarm.status === 'acknowledged').length,
      all: unresolved.length,
    }),
    [unresolved],
  )

  const visible = useMemo(() => {
    if (tab === 'all') return unresolved
    return unresolved.filter((alarm) => alarm.status === tab)
  }, [unresolved, tab])

  return (
    <>
      <SectionCard
        title="Active alarms"
        description="Deviations raised against the current plant selection"
        icon={BellRing}
        actions={
          <div className="flex items-center gap-2">
            <Tabs value={tab} onValueChange={(value) => setTab(value as AlarmTab)}>
              <TabsList>
                <TabsTrigger value="active">
                  Active
                  <Count value={counts.active} />
                </TabsTrigger>
                <TabsTrigger value="acknowledged">
                  Acknowledged
                  <Count value={counts.acknowledged} />
                </TabsTrigger>
                <TabsTrigger value="all">
                  All open
                  <Count value={counts.all} />
                </TabsTrigger>
              </TabsList>
            </Tabs>

            <Button variant="outline" size="sm" asChild className="gap-1">
              <Link to={ROUTES.activeAlarms}>
                View all
                <ChevronRight className="size-3.5" aria-hidden />
              </Link>
            </Button>
          </div>
        }
        bodyClassName="p-0"
        flush
      >
        {visible.length === 0 ? (
          <EmptyState
            icon={BellOff}
            title={
              tab === 'active'
                ? 'No active alarms'
                : tab === 'acknowledged'
                  ? 'Nothing acknowledged'
                  : 'No open alarms'
            }
            description={
              tab === 'active'
                ? 'Every parameter in the current selection is inside its tolerance band, or its alarms have already been acknowledged.'
                : 'No alarms in this state for the current plant selection.'
            }
            compact
          />
        ) : (
          <div className="flex flex-col gap-3 p-4">
            {visible.slice(0, limit).map((alarm) => (
              <AlarmCard
                key={alarm.id}
                alarm={alarm}
                onView={setDetailsAlarm}
                onAcknowledge={actions.requestAcknowledge}
                onResolve={actions.requestResolve}
              />
            ))}

            {visible.length > limit && (
              <Link
                to={ROUTES.activeAlarms}
                className="text-brand hover:bg-surface-muted border-line flex items-center justify-center gap-1 rounded-lg border border-dashed py-2.5 text-[13px] font-medium transition-colors"
              >
                Show {visible.length - limit} more{' '}
                {visible.length - limit === 1 ? 'alarm' : 'alarms'}
                <ChevronRight className="size-3.5" aria-hidden />
              </Link>
            )}
          </div>
        )}
      </SectionCard>

      <AlarmDetailsDialog
        alarm={detailsAlarm}
        open={detailsAlarm !== null}
        onOpenChange={(open) => {
          if (!open) setDetailsAlarm(null)
        }}
        onAcknowledge={(alarm) => {
          setDetailsAlarm(null)
          actions.requestAcknowledge(alarm)
        }}
        onResolve={(alarm) => {
          setDetailsAlarm(null)
          actions.requestResolve(alarm)
        }}
      />

      <AlarmActionDialog actions={actions} />
    </>
  )
}

function Count({ value }: { value: number }) {
  if (value === 0) return null
  return (
    <span className="bg-surface-muted text-ink-soft tnum ml-0.5 rounded px-1.5 text-[11px] font-semibold">
      {value}
    </span>
  )
}
