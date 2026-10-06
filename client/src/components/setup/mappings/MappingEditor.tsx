import { CheckCircle2, FileUp, Loader2, Radar, Save, Tag, TriangleAlert, XCircle } from 'lucide-react'
import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import { SectionCard } from '@/components/shared/SectionCard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { ApiProblem } from '@/services/http'
import { configApi } from '@/services/configApi'
import type { MappingCheck, MappingDiscovery, MappingDraft, MappingRow, MappingsOverview } from '@/types/configApi'
import { cn } from '@/utils/cn'
import { fromManilaInput, toUtcIso } from '@/utils/manilaTime'

import { FormField } from '../FormParts'
import { asProblem, nextHourInput } from '../versionUtils'
import { groupTags, placesFrom, rowsFrom, suggestTopics, tagLeaf, type Place } from './mappingModel'
import { TopicPicker, type TopicOption } from './TopicPicker'

export interface MappingBase {
  /** The version the form starts from; null for an empty mapping. */
  number: number | null
  source: string
  rows: MappingRow[]
}

const LISTEN_S = 10

/** Edits a new mapping version: where each tag monitor-core needs arrives on MQTT. */
export function MappingEditor({
  base,
  overview,
  onCancel,
  onSaved,
}: {
  base: MappingBase
  overview: MappingsOverview
  onCancel: () => void
  onSaved: (overview: MappingsOverview) => void
}) {
  const required = overview.required
  const [places, setPlaces] = useState<Record<string, Place>>(() => placesFrom(base.rows))
  const [source, setSource] = useState(base.source)
  const [reason, setReason] = useState('')
  const [activate, setActivate] = useState<MappingDraft['activate']>('no')
  const [activateAt, setActivateAt] = useState(nextHourInput)
  const [check, setCheck] = useState<MappingCheck | null>(null)
  const [problem, setProblem] = useState<ApiProblem | null>(null)
  const [saving, setSaving] = useState(false)
  const [listening, setListening] = useState(false)
  const [discovery, setDiscovery] = useState<MappingDiscovery | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const rows = useMemo(() => rowsFrom(places, required), [places, required])
  const dropped = base.rows.filter((r) => !required.some((q) => q.tag === r.tag))
  const fieldsOn = useMemo(() => discovery?.fields ?? {}, [discovery])
  const fieldLists = Object.keys(fieldsOn)
  const topicOptions = useMemo<TopicOption[]>(() => {
    const heard = new Set(discovery?.topics ?? [])
    const suggested = new Set(suggestTopics(overview.subscriptions, required))
    const used = new Map<string, number>()
    for (const r of rows) used.set(r.topic, (used.get(r.topic) ?? 0) + 1)
    const all = new Set([...used.keys(), ...heard, ...suggested])
    return [...all].sort().map((topic) => ({ topic, heard: heard.has(topic), suggested: suggested.has(topic), used: used.get(topic) ?? 0 }))
  }, [rows, discovery, overview.subscriptions, required])

  const draftOf = (extra: Partial<MappingDraft> = {}): MappingDraft => ({
    expectedLatest: overview.latest,
    basedOn: base.number,
    rows,
    source,
    reason: '',
    activate: 'no',
    activateAt: null,
    ...extra,
  })

  // Live check: the api's validation, coverage and warnings, a moment after each change
  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      configApi
        .checkMapping(
          { expectedLatest: overview.latest, basedOn: base.number, rows, source, reason: '', activate: 'no', activateAt: null },
          controller.signal,
        )
        .then(setCheck)
        .catch(() => undefined)
    }, 500)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [rows, source, overview.latest, base.number])

  const errors = problem?.fieldErrors.length ? problem.fieldErrors : (check?.errors ?? [])
  const errorAt = (tag: string, field: 'topic' | 'field' | 'tag') => {
    const i = rows.findIndex((r) => r.tag === tag)
    return i < 0 ? undefined : errors.find((e) => e.field === `rows[${i}].${field}`)?.message
  }
  const coverage = check?.coverage
  const complete = coverage !== undefined && coverage.missing.length === 0

  const setPlace = (tag: string, patch: Partial<Place>) => {
    setProblem(null)
    setPlaces((p) => ({ ...p, [tag]: { topic: '', field: '', ...p[tag], ...patch } }))
  }

  /** A topic chosen for a tag; an empty field takes the tag's own name when that was heard on the topic. */
  const chooseTopic = (tag: string, topic: string) => {
    const leaf = tagLeaf(tag)
    const field = places[tag]?.field ?? ''
    setPlace(tag, !field.trim() && fieldsOn[topic]?.includes(leaf) ? { topic, field: leaf } : { topic })
  }
  const fieldListFor = (topic: string) => (fieldsOn[topic] ? `mapping-fields-${fieldLists.indexOf(topic)}` : undefined)

  const listen = async () => {
    setListening(true)
    try {
      const found = await configApi.discoverMapping(LISTEN_S)
      if (!found.connected) {
        toast.error("Couldn't listen to the broker", { description: found.error })
        return
      }
      setDiscovery(found)
      setPlaces((p) => ({ ...p, ...placesFrom(found.rows ?? []) }))
      setSource(`broker, listened ${Math.round(found.listenedS ?? LISTEN_S)} s`)
      setNote(
        `Found ${found.rows?.length ?? 0} of ${required.length} tags in ${Math.round(found.listenedS ?? LISTEN_S)} s` +
          (found.notSeen?.length ? `; not seen: ${found.notSeen.join(', ')}` : '.'),
      )
    } catch (caught) {
      toast.error("Couldn't listen to the broker", { description: asProblem(caught).message })
    } finally {
      setListening(false)
    }
  }

  const importFile = async (file: File) => {
    try {
      const text = await file.text()
      const format = file.name.toLowerCase().endsWith('.csv') ? 'csv' : 'topic-map'
      const got = await configApi.importMapping(format, text)
      setPlaces(placesFrom(got.rows))
      setSource(got.source || file.name)
      setNote(
        [
          `${got.rows.length} of ${required.length} tags from ${file.name}`,
          got.ignored.length ? `${got.ignored.length} not needed and left out (${got.ignored.join(', ')})` : null,
          got.notSeen.length ? `not seen by the probe: ${got.notSeen.join(', ')}` : null,
          ...got.problems.map((p) => `line ${p.line}: ${p.message}`),
        ]
          .filter(Boolean)
          .join('; ') + '.',
      )
    } catch (caught) {
      toast.error(`Couldn't read ${file.name}`, { description: asProblem(caught).message })
    }
  }

  const save = async () => {
    setSaving(true)
    setProblem(null)
    try {
      const at = activate === 'at' ? fromManilaInput(activateAt) : null
      const next = await configApi.saveMapping(draftOf({ reason, activate, activateAt: at === null ? null : toUtcIso(at) }))
      toast.success(`Mapping v${next.created} saved`, {
        description: activate === 'no' ? 'Not in effect until you activate it' : activate === 'now' ? 'Now in effect' : 'Activation scheduled',
      })
      onSaved(next)
    } catch (caught) {
      setProblem(asProblem(caught))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="border-brand/30 bg-brand-surface flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-2.5 text-[13px]">
        <p className="text-ink">
          <b>{overview.latest === null ? 'First mapping' : `New version: Mapping v${overview.latest + 1}`}</b>
          {base.number !== null ? `, starting from Mapping v${base.number}` : ''}. Nothing changes until you save, and nothing
          takes effect until the version is activated.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={onCancel}>
          Discard
        </Button>
      </div>

      <SectionCard
        title="Where each tag arrives"
        description={`The topic, and the JSON field of its message; an empty field means the whole payload. Subscribed: ${overview.subscriptions.join(', ') || 'nothing yet'}`}
        icon={Tag}
        actions={
          <>
            <Button type="button" variant="outline" size="sm" disabled={listening} onClick={() => void listen()}>
              {listening ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Radar className="size-3.5" aria-hidden />}
              {listening ? `Listening ${LISTEN_S} s…` : 'Fill from the broker'}
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => fileInput.current?.click()}>
              <FileUp className="size-3.5" aria-hidden /> Import file
            </Button>
            <input
              ref={fileInput}
              type="file"
              accept=".json,.csv,application/json,text/csv"
              className="hidden"
              aria-label="Mapping file: a probe topic-map.json or a tag,topic,field CSV"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) void importFile(file)
                e.target.value = ''
              }}
            />
          </>
        }
        flush
      >
        <div className="border-line text-ink-soft flex flex-wrap items-center gap-x-4 gap-y-1 border-b px-5 py-2 text-[12px]">
          {coverage ? (
            complete ? (
              <span className="text-normal inline-flex items-center gap-1">
                <CheckCircle2 className="size-3.5" aria-hidden /> Every tag monitor-core needs has a place ({coverage.mapped} of{' '}
                {coverage.required})
              </span>
            ) : (
              <span className="text-warning inline-flex items-center gap-1">
                <TriangleAlert className="size-3.5" aria-hidden /> {coverage.mapped} of {coverage.required} tags have a place; the rest
                can't be monitored
              </span>
            )
          ) : (
            <span>Checking…</span>
          )}
          <span>Source: {source}</span>
          {note && <span className="text-ink">{note}</span>}
        </div>
        {fieldLists.map((topic, i) => (
          <datalist key={topic} id={`mapping-fields-${i}`}>
            {(fieldsOn[topic] ?? []).map((f) => (
              <option key={f} value={f} />
            ))}
          </datalist>
        ))}
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-ink-muted border-line border-b text-left text-[11px] uppercase">
              <th className="w-[300px] px-5 py-2 font-semibold">Tag</th>
              <th className="px-2 py-2 font-semibold">Topic</th>
              <th className="w-[280px] px-2 py-2 font-semibold">Field</th>
              <th className="w-10 px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {groupTags(required).map((g) => (
              <Fragment key={g.key}>
                <tr className="bg-surface-muted/50 border-line-soft border-b">
                  <td colSpan={4} className="px-5 py-1.5 font-medium">
                    {g.title}
                  </td>
                </tr>
                {g.tags.map((t) => {
                  const place = places[t.tag] ?? { topic: '', field: '' }
                  const topicError = errorAt(t.tag, 'topic')
                  const fieldError = errorAt(t.tag, 'field')
                  const mapped = place.topic.trim() !== ''
                  return (
                    <tr key={t.tag} className="border-line-soft border-b align-top">
                      <td className="py-1.5 pr-3 pl-8">
                        <span className="text-ink">{t.label}</span>
                        <span className="text-ink-muted block font-mono text-[11px]">{t.tag}</span>
                      </td>
                      <td className="px-2 py-1.5">
                        <TopicPicker
                          value={place.topic}
                          onChange={(topic) => chooseTopic(t.tag, topic)}
                          options={topicOptions}
                          label={`${t.label} topic`}
                          invalid={Boolean(topicError)}
                        />
                        {topicError && <p className="text-critical mt-1 text-[11px]">{topicError}</p>}
                      </td>
                      <td className="px-2 py-1.5">
                        <Input
                          list={fieldListFor(place.topic)}
                          value={place.field}
                          onChange={(e) => setPlace(t.tag, { field: e.target.value })}
                          placeholder="(whole payload)"
                          className={cn('h-8 font-mono text-[12px]', fieldError && 'border-critical-border')}
                          aria-label={`${t.label} field`}
                        />
                        {fieldError && <p className="text-critical mt-1 text-[11px]">{fieldError}</p>}
                      </td>
                      <td className="px-2 py-2.5">
                        {mapped && !topicError && !fieldError ? (
                          <CheckCircle2 className="text-normal size-4" aria-label="has a place" />
                        ) : (
                          <TriangleAlert className="text-warning size-4" aria-label="no place yet" />
                        )}
                      </td>
                    </tr>
                  )
                })}
              </Fragment>
            ))}
          </tbody>
        </table>
        {dropped.length > 0 && (
          <p className="text-ink-soft border-line border-t px-5 py-2 text-[12px]">
            Left out {dropped.length} row{dropped.length === 1 ? '' : 's'} from Mapping v{base.number} that the register no longer
            needs: {dropped.map((r) => r.tag).join(', ')}.
          </p>
        )}
      </SectionCard>

      <SectionCard title="Save" description="A new version, kept for good; the one in effect stays until you activate another" icon={Save}>
        {check && check.warnings.length > 0 && (
          <ul className="text-warning mb-3 flex flex-col gap-1 text-[12px]">
            {check.warnings.map((w) => (
              <li key={w} className="flex items-start gap-1.5">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {w}
              </li>
            ))}
          </ul>
        )}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1fr]">
          <FormField label="Reason for the change" error={problem?.forField('reason')} hint="Required. Kept with the version.">
            <Textarea
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. From the probe run on the plant broker, 30 Sep"
              className="text-[13px]"
              aria-label="Reason for the change"
            />
          </FormField>
          <fieldset className="flex flex-col gap-2 text-[13px]">
            <legend className="micro-label mb-1.5">After saving</legend>
            <label className="flex items-center gap-2">
              <input type="radio" name="activate" checked={activate === 'no'} onChange={() => setActivate('no')} />
              Keep it saved; activate later
            </label>
            <label className={cn('flex items-center gap-2', !complete && 'opacity-50')}>
              <input type="radio" name="activate" disabled={!complete} checked={activate === 'now'} onChange={() => setActivate('now')} />
              Activate now
            </label>
            <label className={cn('flex flex-wrap items-center gap-2', !complete && 'opacity-50')}>
              <input type="radio" name="activate" disabled={!complete} checked={activate === 'at'} onChange={() => setActivate('at')} />
              Activate at
              <Input
                type="datetime-local"
                value={activateAt}
                disabled={!complete}
                onChange={(e) => {
                  setActivateAt(e.target.value)
                  setActivate('at')
                }}
                className="h-8 w-auto text-[13px]"
                aria-label="Activation time, Manila"
              />
              <span className="text-ink-muted text-[12px]">Manila</span>
            </label>
            {!complete && <p className="text-ink-muted text-[12px]">Activating needs a place for every tag monitor-core needs.</p>}
            {problem?.forField('activateAt') && <p className="text-critical text-[12px]">{problem.forField('activateAt')}</p>}
          </fieldset>
        </div>

        {(errors.length > 0 || (problem && problem.fieldErrors.length === 0)) && (
          <div className="border-critical-border bg-critical-surface mt-4 rounded-md border px-3 py-2 text-[13px]">
            {problem && problem.fieldErrors.length === 0 ? (
              <p className="text-critical flex items-center gap-1.5">
                <XCircle className="size-4 shrink-0" aria-hidden /> {problem.message}
              </p>
            ) : (
              <>
                <p className="text-critical font-medium">
                  {errors.length} thing{errors.length === 1 ? '' : 's'} to fix before saving:
                </p>
                <ul className="text-ink mt-1 list-disc pl-5 text-[12px]">
                  {errors.slice(0, 8).map((e) => (
                    <li key={e.field + e.message}>{e.message}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="outline" size="sm" onClick={onCancel}>
            Discard
          </Button>
          <Button type="button" size="sm" disabled={saving} onClick={() => void save()}>
            {saving ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Save className="size-4" aria-hidden />}
            {activate === 'no' ? 'Save version' : activate === 'now' ? 'Save and activate' : 'Save and schedule'}
          </Button>
        </div>
      </SectionCard>
    </div>
  )
}
