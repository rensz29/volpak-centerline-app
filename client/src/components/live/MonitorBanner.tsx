import { CheckCircle2, Clock, CloudOff, MinusCircle, PauseCircle, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'

import type { ApiProblem } from '@/services/http'
import type { MonitorStatus } from '@/types/monitoringApi'
import { cn } from '@/utils/cn'
import { formatManilaFull } from '@/utils/manilaTime'

import { TONE, duration, type Tone } from './liveModel'

const LATE_S = 10 // monitor-core beats every 2 s; the api calls it not running after 60 s

function Banner({ tone, icon: Icon, title, children }: { tone: Tone; icon: typeof CheckCircle2; title: string; children?: ReactNode }) {
  return (
    <div className={cn('flex items-start gap-2.5 rounded-lg border px-4 py-2.5 text-[13px]', TONE[tone].badge)}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="text-ink min-w-0">
        <p className="font-semibold">{title}</p>
        {children}
      </div>
    </div>
  )
}

/** Whether monitor-core is judging, and if not, why: the first thing on the page. */
export function MonitorBanner({ monitor, error, targets }: {
  monitor: MonitorStatus | null | undefined
  error: ApiProblem | null
  /** How many zones have a target, of how many: only those are judged on HMI (ADR-0027) */
  targets?: { set: number; zones: number }
}) {
  if (error) {
    return (
      <Banner tone="critical" icon={CloudOff} title="Can't reach the live data">
        <p className="text-ink-soft">{error.message}</p>
      </Banner>
    )
  }
  if (monitor === undefined) return null
  if (monitor === null) {
    return (
      <Banner tone="nodata" icon={MinusCircle} title="monitor-core has never run here: nothing is being judged">
        <p className="text-ink-soft">
          Start it as described in services/monitor_core/README.md. Until then the table shows no values or states.
        </p>
      </Banner>
    )
  }
  if (!monitor.alive) {
    return (
      <Banner tone="nodata" icon={MinusCircle} title="monitor-core isn't running: nothing is being judged">
        <p className="text-ink-soft">
          Its last heartbeat was {duration(monitor.ageS * 1000)} ago ({formatManilaFull(Date.parse(monitor.beatAt))} Manila).
          Open events stay open until it runs again.
        </p>
      </Banner>
    )
  }
  if (monitor.ageS > LATE_S) {
    return (
      <Banner tone="warning" icon={Clock} title={`No heartbeat from monitor-core for ${duration(monitor.ageS * 1000)}: the values below may be out of date`}>
        <p className="text-ink-soft">It writes one every 2 s. After 60 s without one, the page treats it as not running.</p>
      </Banner>
    )
  }
  if (!monitor.judging) {
    return (
      <Banner tone="warning" icon={PauseCircle} title="Monitoring paused: values aren't being judged">
        <ul className="text-ink-soft mt-0.5 list-disc pl-4">
          {(monitor.reasons ?? []).map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        <p className="text-ink-muted mt-1 text-[12px]">Open events stay open until judging resumes on a complete, fresh snapshot.</p>
      </Banner>
    )
  }
  // A zone without a target has only its actual value judged (ADR-0027)
  const set = targets?.set ?? 0
  const partial = targets !== undefined && set < targets.zones
  const some = partial ? ` on the ${set} of ${targets.zones} zones with a target` : ''
  const hmiNote = !partial
    ? 'HMI mismatch is judged as usual (ADR-0010)'
    : set === 0
      ? 'HMI mismatch waits for targets on Configuration → Rules (ADR-0027)'
      : `HMI mismatch is judged${some}`
  return (
    <Banner tone={monitor.actualPaused ? 'warning' : 'normal'} icon={monitor.actualPaused ? TriangleAlert : CheckCircle2}
            title={`${partial && set === 0 ? 'Judging actual values' : 'Judging the line'} · Rules v${monitor.rulesVersion} · Mapping v${monitor.mappingVersion}`}>
      <p className="text-ink-soft">
        {monitor.actualPaused
          ? monitor.stop === 'warmup' && monitor.warmupUntil
            ? `Actual Warning/Critical rules are in the warm-up after a long stop until ${formatManilaFull(Date.parse(monitor.warmupUntil))} Manila; ${hmiNote}.`
            : `The machine is stopped: Actual Warning/Critical rules are paused; ${hmiNote}.`
          : partial
            ? set === 0
              ? 'No zone has a target yet: each actual value is judged against its setpoint. Give the zones their targets on Configuration → Rules to judge the HMI setpoints too (ADR-0027).'
              : `Each actual value is judged against its setpoint, and each HMI setpoint against its zone's target${some}. Give the others targets on Configuration → Rules to judge theirs (ADR-0027).`
            : `Register ${monitor.registerVersion} · every change of state is kept as evidence.`}
      </p>
    </Banner>
  )
}
