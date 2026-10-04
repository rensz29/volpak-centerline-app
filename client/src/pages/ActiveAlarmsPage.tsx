import { BellOff, RotateCcw, Search, X } from 'lucide-react'
import { useMemo, useState } from 'react'

import { AlarmCard } from '@/components/alarms/AlarmCard'
import { AlarmDetailsDialog } from '@/components/alarms/AlarmDetailsDialog'
import { AlarmActionDialog, useAlarmActions } from '@/components/alarms/useAlarmActions'
import { EmptyState } from '@/components/shared/EmptyState'
import { ListSkeleton } from '@/components/shared/LoadingSkeleton'
import { PageHeader } from '@/components/shared/PageHeader'
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
import { useCenterline, useScope } from '@/hooks/useCenterline'
import {
  ALARM_SEVERITIES,
  ALARM_SEVERITY_LABELS,
  type AlarmRow,
  type AlarmSeverity,
} from '@/types'

type StatusFilter = 'active' | 'acknowledged' | 'open'

export function ActiveAlarmsPage() {
  const { loading, alarmRows, machines } = useCenterline()
  const scope = useScope()
  const actions = useAlarmActions()

  const [severity, setSeverity] = useState<AlarmSeverity | typeof ALL>(ALL)
  const [status, setStatus] = useState<StatusFilter>('open')
  const [machineId, setMachineId] = useState<string>(ALL)
  const [search, setSearch] = useState('')
  const [detailsAlarm, setDetailsAlarm] = useState<AlarmRow | null>(null)

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()

    return alarmRows
      .filter((alarm) => {
        if (alarm.status === 'resolved') return false
        if (status !== 'open' && alarm.status !== status) return false
        if (severity !== ALL && alarm.severity !== severity) return false
        if (machineId !== ALL && alarm.machineId !== machineId) return false
        if (scope.factoryId !== ALL && alarm.factoryId !== scope.factoryId) return false
        if (scope.lineId !== ALL && alarm.lineId !== scope.lineId) return false
        if (scope.machineId !== ALL && alarm.machineId !== scope.machineId) return false
        if (
          term !== '' &&
          !`${alarm.reference} ${alarm.parameterName} ${alarm.machineName} ${alarm.skuCode} ${alarm.message}`
            .toLowerCase()
            .includes(term)
        ) {
          return false
        }
        return true
      })
      .sort((a, b) => b.raisedAt.localeCompare(a.raisedAt))
  }, [alarmRows, status, severity, machineId, search, scope])

  const activeFilters =
    (severity !== ALL ? 1 : 0) +
    (status !== 'open' ? 1 : 0) +
    (machineId !== ALL ? 1 : 0) +
    (search.trim() !== '' ? 1 : 0)

  const reset = () => {
    setSeverity(ALL)
    setStatus('open')
    setMachineId(ALL)
    setSearch('')
    scope.reset()
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Active Alarms"
        description="Unresolved centerline deviations awaiting acknowledgement or resolution."
        breadcrumbs={[{ label: 'Alarms' }, { label: 'Active Alarms' }]}
      />

      <div className="bg-surface border-line shadow-card rounded-lg border">
        <div className="border-line flex items-center justify-between gap-3 border-b px-4 py-2.5">
          <p className="text-ink-soft text-[13px]">
            <span className="tnum text-ink font-medium">{filtered.length}</span> open{' '}
            {filtered.length === 1 ? 'alarm' : 'alarms'}
          </p>
          <Button
            variant="ghost"
            size="sm"
            onClick={reset}
            disabled={activeFilters === 0}
            className="gap-1.5"
          >
            <RotateCcw className="size-3.5" aria-hidden />
            Reset filters
          </Button>
        </div>

        <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Status">
            <Select value={status} onValueChange={(value) => setStatus(value as StatusFilter)}>
              <SelectTrigger aria-label="Filter by alarm status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="open">All open</SelectItem>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="acknowledged">Acknowledged</SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <Field label="Severity">
            <Select
              value={severity}
              onValueChange={(value) => setSeverity(value as AlarmSeverity | typeof ALL)}
            >
              <SelectTrigger aria-label="Filter by severity">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All severities</SelectItem>
                {ALARM_SEVERITIES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {ALARM_SEVERITY_LABELS[value]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field label="Machine">
            <Select value={machineId} onValueChange={setMachineId}>
              <SelectTrigger aria-label="Filter by machine">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All machines</SelectItem>
                {machines.map((machine) => (
                  <SelectItem key={machine.id} value={machine.id}>
                    {machine.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field label="Search">
            <div className="relative">
              <Search
                className="text-ink-muted pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
                aria-hidden
              />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Reference, parameter, message…"
                aria-label="Search alarms"
                className="pr-9 pl-9"
              />
              {search !== '' && (
                <button
                  type="button"
                  onClick={() => setSearch('')}
                  className="text-ink-muted hover:text-ink absolute top-1/2 right-2 grid size-6 -translate-y-1/2 place-items-center rounded"
                  aria-label="Clear search"
                >
                  <X className="size-3.5" aria-hidden />
                </button>
              )}
            </div>
          </Field>
        </div>
      </div>

      {loading ? (
        <ListSkeleton rows={4} />
      ) : filtered.length === 0 ? (
        <div className="bg-surface border-line shadow-card rounded-lg border">
          <EmptyState
            icon={BellOff}
            title="No open alarms"
            description="Nothing matches the current filters. Every parameter in this selection is either inside tolerance or its alarms have been resolved."
            action={
              activeFilters > 0 ? (
                <Button variant="outline" size="sm" onClick={reset}>
                  Reset filters
                </Button>
              ) : undefined
            }
          />
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {filtered.map((alarm) => (
            <AlarmCard
              key={alarm.id}
              alarm={alarm}
              onView={setDetailsAlarm}
              onAcknowledge={actions.requestAcknowledge}
              onResolve={actions.requestResolve}
            />
          ))}
        </div>
      )}

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
    </div>
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
