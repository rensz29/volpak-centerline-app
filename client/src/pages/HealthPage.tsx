import { AlertOctagon, AlertTriangle, ArrowRight, CheckCircle2, MinusCircle, RefreshCw, type LucideIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import type { Tone } from '@/components/live/liveModel'
import { StateBadge } from '@/components/live/StateBadge'
import { TableSkeleton } from '@/components/shared/LoadingSkeleton'
import { PageHeader } from '@/components/shared/PageHeader'
import { SectionCard } from '@/components/shared/SectionCard'
import { Button } from '@/components/ui/button'
import { ApiProblem } from '@/services/http'
import { healthApi } from '@/services/healthApi'
import type { HealthCheck, HealthReport, HealthState } from '@/types/healthApi'
import { cn } from '@/utils/cn'
import { formatManilaFull } from '@/utils/manilaTime'

const EVERY_MS = 15_000

const LOOK: Record<HealthState, { tone: Tone; icon: LucideIcon; label: string }> = {
  ok: { tone: 'normal', icon: CheckCircle2, label: 'OK' },
  warning: { tone: 'warning', icon: AlertTriangle, label: 'Warning' },
  critical: { tone: 'critical', icon: AlertOctagon, label: 'Critical' },
  unknown: { tone: 'nodata', icon: MinusCircle, label: 'Not measured' },
}

const BANNER: Record<HealthState, string> = {
  ok: 'border-normal-border bg-normal-surface',
  unknown: 'border-normal-border bg-normal-surface',
  warning: 'border-warning-border bg-warning-surface',
  critical: 'border-critical-border bg-critical-surface',
}

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`
}

/** One line for the whole system, then the checks that need someone, each a jump to its row. */
function Verdict({ report }: { report: HealthReport }) {
  const critical = report.checks.filter((c) => c.state === 'critical')
  const warning = report.checks.filter((c) => c.state === 'warning')
  const unknown = report.checks.filter((c) => c.state === 'unknown')
  const attention = [...critical, ...warning]
  const { icon: Icon, tone } = LOOK[report.overall === 'unknown' ? 'ok' : report.overall]
  const headline = attention.length
    ? [critical.length && plural(critical.length, 'critical check', 'critical checks'), warning.length && plural(warning.length, 'warning', 'warnings')]
        .filter(Boolean)
        .join(' and ') + ': start with the first below'
    : `Everything is running as it should: ${plural(report.checks.length - unknown.length, 'check is', 'checks are')} OK${
        unknown.length ? `, and ${unknown.length} can't be measured on this setup` : ''
      }`
  return (
    <div className={cn('flex items-start gap-3 rounded-lg border px-4 py-3', BANNER[report.overall])}>
      <Icon className={cn('mt-0.5 size-5 shrink-0', tone === 'normal' ? 'text-normal' : tone === 'warning' ? 'text-warning' : 'text-critical')} aria-hidden />
      <div className="min-w-0">
        <p className="text-ink text-[14px] font-semibold">{headline}</p>
        {attention.length > 0 && (
          <ul className="mt-1.5 flex flex-col gap-1 text-[13px]">
            {attention.map((c) => (
              <li key={c.id}>
                <a href={`#${c.id}`} className="text-ink hover:underline">
                  <span className="font-medium">{c.title}:</span> <span className="text-ink-soft">{c.summary}</span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function CheckRow({ check }: { check: HealthCheck }) {
  const look = LOOK[check.state]
  return (
    <li id={check.id} className="border-line-soft grid scroll-mt-20 grid-cols-[130px_minmax(0,1fr)_auto] items-start gap-3 border-b px-5 py-3 last:border-b-0 max-sm:grid-cols-1 max-sm:gap-1.5">
      <StateBadge tone={look.tone} icon={look.icon} label={look.label} className="justify-self-start" />
      <div className="min-w-0">
        <p className="text-ink text-[13px] font-medium">{check.title}</p>
        <p className="text-ink-soft text-[13px] break-words">{check.summary}</p>
      </div>
      {check.link ? (
        <Link to={check.link} className="text-brand inline-flex items-center gap-1 text-[12px] font-medium hover:underline">
          Open <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      ) : (
        <span aria-hidden />
      )}
    </li>
  )
}

/**
 * System health (ADR-0038), for Administrators: each part of Centerline graded by the api from what it reports:
 * monitor-core, the notifier, the disk, the backups, the database, the malware scanner and Timebase.
 */
export function HealthPage() {
  const [report, setReport] = useState<HealthReport | null>(null)
  const [problem, setProblem] = useState<ApiProblem | null>(null)
  const [busy, setBusy] = useState(false)
  const checkNow = useRef<() => void>(() => undefined)

  // Every 15 s while the page is visible; "Check now" runs the same load at once
  useEffect(() => {
    const controller = new AbortController()
    let timer: number | undefined
    const load = async () => {
      window.clearTimeout(timer)
      if (document.visibilityState === 'visible') {
        setBusy(true)
        try {
          setReport(await healthApi.report(controller.signal))
          setProblem(null)
        } catch (caught) {
          if (caught instanceof DOMException && caught.name === 'AbortError') return
          setProblem(caught instanceof ApiProblem ? caught : new ApiProblem(0, { detail: String(caught) }))
        } finally {
          setBusy(false)
        }
      }
      timer = window.setTimeout(() => void load(), EVERY_MS)
    }
    checkNow.current = () => void load()
    void load()
    const onVisible = () => document.visibilityState === 'visible' && void load()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])

  const areas = report ? [...new Set(report.checks.map((c) => c.area))] : []

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="System health"
        description="Each part of Centerline as it reports itself: monitoring, notifications, storage and backups, the database, uploads and history."
        breadcrumbs={[{ label: 'Setup' }, { label: 'System health' }]}
        actions={
          <div className="flex items-center gap-3">
            {report && <span className="text-ink-muted text-[12px]">Checked {formatManilaFull(Date.parse(report.checkedAt))} Manila</span>}
            <Button type="button" variant="outline" size="sm" onClick={() => checkNow.current()} disabled={busy}>
              <RefreshCw className={cn('size-4', busy && 'animate-spin')} aria-hidden />
              Check now
            </Button>
          </div>
        }
      />

      {problem && (
        <div className="border-critical-border bg-critical-surface text-ink rounded-lg border px-4 py-3 text-[13px]">
          <p className="font-semibold">Can't get the system's health</p>
          <p className="text-ink-soft">{problem.message}</p>
        </div>
      )}

      {!report ? (
        !problem && (
          <SectionCard title="Checking every part" flush>
            <TableSkeleton rows={8} columns={3} />
          </SectionCard>
        )
      ) : (
        <>
          <Verdict report={report} />
          {areas.map((area) => {
            const checks = report.checks.filter((c) => c.area === area)
            const worst = checks.filter((c) => c.state === 'critical' || c.state === 'warning').length
            return (
              <SectionCard key={area} title={area} description={worst ? `${plural(worst, 'check needs', 'checks need')} attention` : 'All as it should be'} flush>
                <ul>
                  {checks.map((c) => (
                    <CheckRow key={c.id} check={c} />
                  ))}
                </ul>
              </SectionCard>
            )
          })}
        </>
      )}
    </div>
  )
}
