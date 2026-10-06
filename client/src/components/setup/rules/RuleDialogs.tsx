import { CheckCircle2, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'

import { configApi } from '@/services/configApi'
import type { ReadinessGap, RulesVersion } from '@/types/configApi'
import { cn } from '@/utils/cn'

const zones = (n: number) => `${n} zone${n === 1 ? '' : 's'}`
const listed = (gaps: ReadinessGap[]) =>
  gaps.length <= 6 ? gaps.map((g) => g.label).join(', ') : `${gaps.slice(0, 6).map((g) => g.label).join(', ')} and ${gaps.length - 6} more`

/** What a version leaves the zones without: limits (the line isn't judged) or a target (that zone's HMI setpoint isn't). */
export function GapsSummary({ gaps, className }: { gaps: ReadinessGap[]; className?: string }) {
  const noLimits = gaps.filter((g) => g.missing.some((f) => f !== 'target'))
  const noTarget = gaps.filter((g) => g.missing.includes('target'))
  return (
    <div className={cn('flex flex-col gap-1', className)}>
      {noLimits.length > 0 ? (
        <p className="text-warning flex items-start gap-1.5">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>
            {zones(noLimits.length)} without all four Warning and Critical limits, so the line isn't judged (OPC-08):{' '}
            <span className="text-ink-soft">{listed(noLimits)}</span>
          </span>
        </p>
      ) : (
        <p className="flex items-center gap-1.5">
          <CheckCircle2 className="text-normal size-3.5 shrink-0" aria-hidden />
          Every zone has its limits: the line is judged.
        </p>
      )}
      {noTarget.length > 0 ? (
        <p className="text-ink-soft">
          {zones(noTarget.length)} without a target: the actual value is judged, the HMI setpoint isn't. {listed(noTarget)}
        </p>
      ) : (
        <p className="text-ink-soft">Every zone has a target, so the HMI setpoints are judged too.</p>
      )}
    </div>
  )
}

/** What a version would judge, shown before activating it. */
export function RulesReadiness({ number }: { number: number }) {
  const [version, setVersion] = useState<RulesVersion | null>(null)

  useEffect(() => {
    configApi
      .rulesVersion(number)
      .then(setVersion)
      .catch(() => setVersion(null))
  }, [number])

  if (!version) return null
  return (
    <div className="border-line rounded-md border px-3 py-2 text-[13px]">
      <p className="text-ink font-medium">What v{number} judges</p>
      <GapsSummary gaps={version.gaps} className="mt-1 text-[12px]" />
    </div>
  )
}
