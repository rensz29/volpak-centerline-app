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
  /** How many zones have a target, of how many: under a placeholder SKU only those are judged on HMI (ADR-0022) */
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
  // A placeholder SKU stands in for the missing SKU field: actual values, and the HMI setpoints of the zones
  // the Rules tab gives it a target (ADR-0022, amended 2026-10-02)
  const placeholder = Boolean(monitor.skuPlaceholder) && monitor.sku === monitor.skuPlaceholder
  const set = targets?.set ?? 0
  const some = targets && set < targets.zones ? ` on the ${set} of ${targets.zones} zones with a target` : ''
  const hmiNote = !placeholder
    ? 'HMI mismatch is judged as usual (ADR-0010)'
    : set === 0
      ? 'HMI mismatch waits for targets or the SKU field (ADR-0022)'
      : `HMI mismatch is judged against the placeholder's targets${some}`
  return (
    <Banner tone={monitor.actualPaused ? 'warning' : 'normal'} icon={monitor.actualPaused ? TriangleAlert : CheckCircle2}
            title={`${placeholder ? `Judging ${set === 0 ? 'actual values ' : ''}under the placeholder SKU ${monitor.sku}` : `Judging SKU ${monitor.sku}`} · Rules v${monitor.rulesVersion} · Mapping v${monitor.mappingVersion}`}>
      <p className="text-ink-soft">
        {monitor.actualPaused
          ? monitor.stop === 'warmup' && monitor.warmupUntil
            ? `Actual Warning/Critical rules are in the warm-up after a long stop until ${formatManilaFull(Date.parse(monitor.warmupUntil))} Manila; ${hmiNote}.`
            : `The machine is stopped: Actual Warning/Critical rules are paused; ${hmiNote}.`
          : placeholder
            ? set === 0
              ? "The machine doesn't publish its SKU yet (O-15): each actual value is judged against its setpoint. HMI mismatch waits for targets on Configuration → Rules, or the SKU field (ADR-0022)."
              : `The machine doesn't publish its SKU yet (O-15): each actual value is judged against its setpoint, and each HMI setpoint against the placeholder's target on Configuration → Rules${some}. After a product change, update the targets (ADR-0022).`
            : `Register ${monitor.registerVersion} · every change of state is kept as evidence.`}
      </p>
    </Banner>
  )
}
