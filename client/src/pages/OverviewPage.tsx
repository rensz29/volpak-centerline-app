import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  BellRing,
  CheckCircle2,
  ChevronRight,
  Cpu,
  Factory as FactoryIcon,
  Gauge,
  TriangleAlert,
} from 'lucide-react'
import { useMemo } from 'react'
import { Link } from 'react-router-dom'

import { AlarmSeverityBadge, AlarmStatusBadge } from '@/components/alarms/AlarmBadges'
import { CardGridSkeleton, ListSkeleton } from '@/components/shared/LoadingSkeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { PageHeader } from '@/components/shared/PageHeader'
import { SectionCard } from '@/components/shared/SectionCard'
import { StatusDot } from '@/components/shared/StatusBadge'
import { SummaryCard } from '@/components/shared/SummaryCard'
import { Button } from '@/components/ui/button'
import { useCenterline } from '@/hooks/useCenterline'
import { ROUTES } from '@/routes/navigation'
import type { CenterlineRow, LineStatus, MachineStatus } from '@/types'
import { cn } from '@/utils/cn'
import { formatDeviationPct, formatRelativeTime } from '@/utils/format'
import { countByStatus } from '@/utils/status'

const LINE_STATUS_META: Record<LineStatus, { label: string; dot: string; text: string }> = {
  running: { label: 'Running', dot: 'bg-normal-solid', text: 'text-normal' },
  idle: { label: 'Idle', dot: 'bg-nodata-solid', text: 'text-nodata' },
  changeover: { label: 'Changeover', dot: 'bg-warning-solid', text: 'text-warning' },
  down: { label: 'Down', dot: 'bg-critical-solid', text: 'text-critical' },
}

const MACHINE_STATUS_META: Record<MachineStatus, { label: string; dot: string }> = {
  running: { label: 'Running', dot: 'bg-normal-solid' },
  idle: { label: 'Idle', dot: 'bg-nodata-solid' },
  maintenance: { label: 'Maintenance', dot: 'bg-warning-solid' },
  offline: { label: 'Offline', dot: 'bg-critical-solid' },
}

export function OverviewPage() {
  const { loading, centerlineRows, alarmRows, factories, lines, machines } = useCenterline()

  const counts = useMemo(
    () => countByStatus(centerlineRows.map((row) => row.status)),
    [centerlineRows],
  )

  const activeAlarms = alarmRows.filter((alarm) => alarm.status === 'active')

  const worstOffenders = useMemo(
    () =>
      centerlineRows
        .filter((row) => row.status === 'critical' || row.status === 'warning')
        .sort(
          (a, b) => Math.abs(b.deviationPct ?? 0) - Math.abs(a.deviationPct ?? 0),
        )
        .slice(0, 6),
    [centerlineRows],
  )

  const setpointDrift = useMemo(
    () => centerlineRows.filter((row) => row.hasSetpointDrift),
    [centerlineRows],
  )

  const conformance =
    centerlineRows.length === 0
      ? 0
      : (counts.normal / centerlineRows.length) * 100

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Plant Overview"
        description="Centerline conformance across every factory, line and machine."
        breadcrumbs={[{ label: 'Monitoring' }, { label: 'Overview' }]}
        actions={
          <Button asChild variant="outline" size="sm" className="gap-1.5">
            <Link to={ROUTES.centerline}>
              Open Digital Centerline
              <ChevronRight className="size-3.5" aria-hidden />
            </Link>
          </Button>
        }
      />

      {loading ? (
        <CardGridSkeleton count={5} />
      ) : (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
          <SummaryCard
            label="Centerline conformance"
            value={`${conformance.toFixed(0)}%`}
            supportingText={`${counts.normal} of ${centerlineRows.length} parameters on target`}
            icon={Gauge}
            tone={conformance >= 80 ? 'normal' : conformance >= 60 ? 'warning' : 'critical'}
            trend={3}
          />
          <SummaryCard
            label="Warning"
            value={counts.warning}
            supportingText="Beyond the warning tolerance"
            icon={AlertTriangle}
            tone="warning"
            trend={-1}
            invertTrendColor
          />
          <SummaryCard
            label="Critical"
            value={counts.critical}
            supportingText="Outside the critical tolerance"
            icon={AlertOctagon}
            tone="critical"
            trend={1}
            invertTrendColor
          />
          <SummaryCard
            label="Setpoint drift"
            value={setpointDrift.length}
            supportingText="HMI values not matching the target"
            icon={TriangleAlert}
            tone={setpointDrift.length > 0 ? 'warning' : 'normal'}
          />
          <SummaryCard
            label="Active alarms"
            value={activeAlarms.length}
            supportingText="Awaiting acknowledgement"
            icon={BellRing}
            tone={activeAlarms.length > 0 ? 'critical' : 'normal'}
            trend={1}
            invertTrendColor
          />
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        {/* Plant hierarchy */}
        <SectionCard
          title="Plant status"
          description="Every factory, line and machine in the mock dataset"
          icon={FactoryIcon}
          className="xl:col-span-2"
          bodyClassName="p-0"
          flush
        >
          {loading ? (
            <ListSkeleton rows={3} />
          ) : (
            <ul className="divide-line divide-y">
              {factories.map((factory) => {
                const factoryLines = lines.filter((line) => line.factoryId === factory.id)
                return (
                  <li key={factory.id} className="px-5 py-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <h3 className="text-ink text-[14px] font-semibold">
                          {factory.name}
                        </h3>
                        <p className="text-ink-soft text-[12px]">
                          {factory.code} · {factory.location}
                        </p>
                      </div>
                      <span className="text-ink-muted tnum shrink-0 text-[12px]">
                        {factoryLines.length}{' '}
                        {factoryLines.length === 1 ? 'line' : 'lines'}
                      </span>
                    </div>

                    <ul className="mt-3 space-y-2">
                      {factoryLines.map((line) => {
                        const lineMachines = machines.filter((m) => m.lineId === line.id)
                        const lineRows = centerlineRows.filter(
                          (row) => row.reading.lineId === line.id,
                        )
                        const lineCounts = countByStatus(lineRows.map((r) => r.status))
                        const meta = LINE_STATUS_META[line.status]

                        return (
                          <li
                            key={line.id}
                            className="border-line bg-surface-muted rounded-md border px-3 py-2.5"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="flex min-w-0 items-center gap-2">
                                <span
                                  className={cn('size-2 shrink-0 rounded-full', meta.dot)}
                                  aria-hidden
                                />
                                <span className="text-ink truncate text-[13px] font-medium">
                                  {line.name}
                                </span>
                                <span className={cn('text-[11px] font-medium', meta.text)}>
                                  {meta.label}
                                </span>
                              </div>

                              <div className="flex shrink-0 items-center gap-2.5 text-[11px]">
                                <StatusCount count={lineCounts.normal} tone="normal" />
                                <StatusCount count={lineCounts.warning} tone="warning" />
                                <StatusCount count={lineCounts.critical} tone="critical" />
                                <StatusCount count={lineCounts['no-data']} tone="nodata" />
                              </div>
                            </div>

                            <ul className="mt-2 flex flex-wrap gap-1.5">
                              {lineMachines.map((machine) => {
                                const machineMeta = MACHINE_STATUS_META[machine.status]
                                return (
                                  <li
                                    key={machine.id}
                                    className="border-line bg-surface text-ink-soft inline-flex items-center gap-1.5 rounded border px-2 py-1 text-[11px]"
                                  >
                                    <Cpu className="text-ink-muted size-3" aria-hidden />
                                    {machine.name}
                                    <span
                                      className={cn(
                                        'size-1.5 rounded-full',
                                        machineMeta.dot,
                                      )}
                                      title={machineMeta.label}
                                      aria-label={machineMeta.label}
                                    />
                                  </li>
                                )
                              })}
                            </ul>
                          </li>
                        )
                      })}
                    </ul>
                  </li>
                )
              })}
            </ul>
          )}
        </SectionCard>

        <div className="flex flex-col gap-5">
          {/* Largest deviations */}
          <SectionCard
            title="Largest deviations"
            description="Parameters furthest from their centerline"
            icon={Activity}
            bodyClassName="p-0"
            flush
          >
            {loading ? (
              <ListSkeleton rows={3} />
            ) : worstOffenders.length === 0 ? (
              <EmptyState
                icon={CheckCircle2}
                title="Everything on target"
                description="No parameter is outside its warning tolerance."
                compact
              />
            ) : (
              <ul className="divide-line-soft divide-y">
                {worstOffenders.map((row) => (
                  <DeviationRow key={row.id} row={row} />
                ))}
              </ul>
            )}
          </SectionCard>

          {/* Recent alarms */}
          <SectionCard
            title="Recent alarms"
            description="Newest unresolved deviations"
            icon={BellRing}
            actions={
              <Button asChild variant="ghost" size="sm" className="gap-1">
                <Link to={ROUTES.activeAlarms}>
                  All
                  <ChevronRight className="size-3.5" aria-hidden />
                </Link>
              </Button>
            }
            bodyClassName="p-0"
            flush
          >
            {loading ? (
              <ListSkeleton rows={3} />
            ) : activeAlarms.length === 0 ? (
              <EmptyState
                icon={CheckCircle2}
                title="No active alarms"
                description="Nothing is currently awaiting acknowledgement."
                compact
              />
            ) : (
              <ul className="divide-line-soft divide-y">
                {activeAlarms.slice(0, 5).map((alarm) => (
                  <li key={alarm.id} className="px-4 py-3">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-ink text-[13px] font-medium">
                        {alarm.parameterName}
                      </p>
                      <span className="text-ink-muted tnum shrink-0 text-[11px]">
                        {formatRelativeTime(alarm.raisedAt)}
                      </span>
                    </div>
                    <p className="text-ink-soft mt-0.5 text-[12px]">
                      {alarm.machineName} · {alarm.skuCode}
                    </p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <AlarmSeverityBadge severity={alarm.severity} />
                      <AlarmStatusBadge status={alarm.status} />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
        </div>
      </div>
    </div>
  )
}

function DeviationRow({ row }: { row: CenterlineRow }) {
  return (
    <li className="flex items-center gap-3 px-4 py-2.5">
      <StatusDot status={row.status} />
      <div className="min-w-0 flex-1">
        <p className="text-ink truncate text-[13px] font-medium">{row.parameter.name}</p>
        <p className="text-ink-muted truncate text-[11px]">
          {row.machineName} · {row.skuCode}
        </p>
      </div>
      <span
        className={cn(
          'tnum shrink-0 text-[13px] font-semibold',
          row.status === 'critical' ? 'text-critical' : 'text-warning',
        )}
      >
        {formatDeviationPct(row.deviationPct)}
      </span>
    </li>
  )
}

function StatusCount({
  count,
  tone,
}: {
  count: number
  tone: 'normal' | 'warning' | 'critical' | 'nodata'
}) {
  if (count === 0) return null
  const classes = {
    normal: 'bg-normal-surface text-normal border-normal-border',
    warning: 'bg-warning-surface text-warning border-warning-border',
    critical: 'bg-critical-surface text-critical border-critical-border',
    nodata: 'bg-nodata-surface text-nodata border-nodata-border',
  }[tone]

  return (
    <span className={cn('tnum rounded border px-1.5 py-0.5 font-semibold', classes)}>
      {count}
    </span>
  )
}
