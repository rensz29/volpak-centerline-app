import { ChevronDown, ChevronRight, History, ListTree, Pencil, TriangleAlert } from 'lucide-react'
import { Fragment, useState } from 'react'

import { SectionCard } from '@/components/shared/SectionCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { AuditEntry, LatestValue, ParameterStatus, RegisterParameter, RegisterView } from '@/types/configApi'
import { formatManilaFull } from '@/utils/manilaTime'

import { STATUS_LABELS } from './labels'

const STATUS_VARIANT: Record<ParameterStatus, 'normal' | 'default' | 'neutral'> = {
  active: 'normal',
  analytics_only: 'default',
  awaiting_tag: 'neutral',
}

function Value({ tag, latest, unit }: { tag: string | null; latest: Record<string, LatestValue | null>; unit: string | null }) {
  if (!tag) return <span className="text-ink-muted text-[12px]">—</span>
  const v = latest[tag]
  return (
    <span className="flex min-w-0 flex-col">
      <span className="truncate font-mono text-[12px]" title={tag}>
        {tag}
      </span>
      <span className="text-ink-muted text-[11px]">
        {v === undefined ? 'loading…' : v === null ? (
          <span className="text-critical inline-flex items-center gap-1">
            <TriangleAlert className="size-3" aria-hidden /> not in Timebase
          </span>
        ) : (
          `now ${String(v.value)}${unit ? ` ${unit}` : ''}`
        )}
      </span>
    </span>
  )
}

/** The parameter register: URS parameters, their zones and Timebase tags, with live values. */
export function TagRegister({
  view,
  latest,
  onEdit,
}: {
  view: RegisterView
  latest: Record<string, LatestValue | null>
  /** Absent when the account can't change the register (Administrator only, ADR-0016). */
  onEdit?: (p: RegisterParameter) => void
}) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(view.parameters.filter((p) => p.zones.length).map((p) => p.id)))
  const toggle = (id: string) =>
    setOpen((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const zones = view.parameters.reduce((n, p) => n + p.zones.length, 0)

  return (
    <SectionCard
      title="Parameters and tags"
      description={`${view.line?.name ?? 'Line'} · register version ${view.version} · ${zones} zones`}
      icon={ListTree}
      flush
    >
      <p className="text-ink-soft border-line border-b px-5 py-2 text-[12px]">
        Tags are Timebase names under <code className="text-[11px]">{view.namespace}</code>. Parameters are the URS
        register (P01–P11); edit a parameter to add zones and pick their tags.
      </p>
      <table className="w-full text-[13px]">
        <thead>
          <tr className="text-ink-muted border-line border-b text-left text-[11px] uppercase">
            <th className="w-8 px-3 py-2" />
            <th className="px-3 py-2 font-semibold">Parameter</th>
            <th className="px-3 py-2 font-semibold">Use</th>
            <th className="px-3 py-2 font-semibold">Zones</th>
            <th className="px-3 py-2 text-right font-semibold" />
          </tr>
        </thead>
        <tbody>
          {view.parameters.map((p) => {
            const expanded = open.has(p.id)
            return (
              <Fragment key={p.id}>
                <tr className="border-line-soft border-b">
                  <td className="px-3 py-2">
                    {p.zones.length > 0 && (
                      <button
                        type="button"
                        onClick={() => toggle(p.id)}
                        className="text-ink-muted hover:text-ink grid size-6 place-items-center rounded"
                        aria-label={expanded ? `Hide ${p.name} zones` : `Show ${p.name} zones`}
                        aria-expanded={expanded}
                      >
                        {expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span className="text-ink font-medium">{p.name}</span>
                    {p.unit && <span className="text-ink-muted"> ({p.unit})</span>}
                    <span className="text-ink-muted ml-2 text-[11px]">{p.id}</span>
                    {p.review && (
                      <span className="text-warning ml-2 inline-flex items-center gap-1 text-[11px]" title={p.review}>
                        <TriangleAlert className="size-3" aria-hidden /> under review
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant={STATUS_VARIANT[p.status]}>{STATUS_LABELS[p.status]}</Badge>
                  </td>
                  <td className="text-ink-soft px-3 py-2">
                    {p.zones.length ? p.zones.map((z) => z.name).join(', ') : p.note ? <span className="text-[12px]">{p.note}</span> : '—'}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {onEdit && (
                      <Button type="button" variant="outline" size="sm" onClick={() => onEdit(p)}>
                        <Pencil className="size-3.5" aria-hidden /> Edit
                      </Button>
                    )}
                  </td>
                </tr>
                {expanded &&
                  p.zones.map((z) => (
                    <tr key={`${p.id}.${z.id}`} className="bg-surface-muted/40 border-line-soft border-b">
                      <td />
                      <td className="py-1.5 pr-3 pl-6">
                        <span className="text-ink">{z.name}</span>
                        <span className="text-ink-muted ml-2 font-mono text-[11px]">{z.id}</span>
                      </td>
                      <td className="max-w-[320px] px-3 py-1.5" colSpan={1}>
                        <span className="micro-label">Setpoint</span>
                        <Value tag={z.setpoint} latest={latest} unit={p.unit} />
                      </td>
                      <td className="max-w-[320px] px-3 py-1.5" colSpan={2}>
                        <span className="micro-label">Actual</span>
                        <Value tag={z.actual} latest={latest} unit={p.unit} />
                      </td>
                    </tr>
                  ))}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </SectionCard>
  )
}

export function RecentChanges({ entries }: { entries: AuditEntry[] }) {
  return (
    <SectionCard title="Change history" description="Every change on this page: when, what and why" icon={History} flush>
      {entries.length === 0 ? (
        <p className="text-ink-muted px-5 py-4 text-[13px]">No changes yet.</p>
      ) : (
        <ul className="divide-line-soft divide-y">
          {entries.map((e, i) => (
            <li key={`${e.at}-${i}`} className="px-5 py-2.5 text-[13px]">
              <p className="text-ink">{e.summary ?? e.action}</p>
              <p className="text-ink-muted text-[12px]">
                {formatManilaFull(Date.parse(e.at))} Manila
                {e.to ? ` · version ${e.to}` : ''}
                {e.reason ? ` · “${e.reason}”` : ''}
                {' · '}
                {e.user ?? 'not recorded'}
              </p>
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  )
}
