import { Loader2, Plus, Save, Trash2, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { ApiProblem } from '@/services/http'
import { configApi } from '@/services/configApi'
import type { HistorianTag, ParameterStatus, RegisterParameter, RegisterView } from '@/types/configApi'

import { FormField } from './FormParts'
import { STATUS_HELP, STATUS_LABELS } from './labels'
import { TagPicker } from './TagPicker'

interface EditZone {
  key: string
  id: string
  name: string
  setpoint: string | null
  actual: string | null
  idEdited: boolean
}

let keySeq = 0
const nextKey = () => `z${++keySeq}`

/** "Front top 2" → "FRONT_TOP_2", the zone ID format the register uses. */
function zoneIdFrom(name: string): string {
  return name.trim().toUpperCase().replace(/[^A-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 16)
}

export function ParameterEditor({
  parameter,
  version,
  onClose,
  onSaved,
}: {
  parameter: RegisterParameter
  version: string
  onClose: () => void
  onSaved: (view: RegisterView) => void
}) {
  // Mounted fresh for each parameter (keyed by the page), so state starts from its props.
  const [status, setStatus] = useState<ParameterStatus>(parameter.status)
  const [zones, setZones] = useState<EditZone[]>(() =>
    parameter.zones.map((z) => ({ key: nextKey(), ...z, idEdited: true })),
  )
  const [reason, setReason] = useState('')
  const [tags, setTags] = useState<HistorianTag[]>([])
  const [tagError, setTagError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [problem, setProblem] = useState<ApiProblem | null>(null)

  useEffect(() => {
    configApi
      .tags('')
      .then((r) => setTags(r.tags))
      .catch((caught: unknown) => setTagError(caught instanceof Error ? caught.message : String(caught)))
  }, [])

  const update = (key: string, patch: Partial<EditZone>) =>
    setZones((list) => list.map((z) => (z.key === key ? { ...z, ...patch } : z)))
  const err = (field: string) => problem?.forField(field)

  const save = async () => {
    setSaving(true)
    setProblem(null)
    try {
      const view = await configApi.saveParameter(parameter.id, {
        baseVersion: version,
        status,
        reason,
        zones: zones.map(({ id, name, setpoint, actual }) => ({ id, name, setpoint, actual })),
      })
      toast.success(`${parameter.name} saved`, { description: `Register version ${view.version}` })
      onSaved(view)
    } catch (caught) {
      setProblem(caught instanceof ApiProblem ? caught : new ApiProblem(0, { detail: String(caught) }))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[920px]">
        <DialogHeader>
          <DialogTitle>
            {parameter.name}
            {parameter.unit ? ` (${parameter.unit})` : ''}
            <span className="text-ink-muted ml-2 text-[12px] font-normal">{parameter.id}</span>
          </DialogTitle>
          <DialogDescription>
            Each zone is a setpoint/actual pair of Timebase tags. Changes are checked against Timebase, versioned and
            kept in the change history.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <FormField label="Use" error={err('status')} hint={STATUS_HELP[status]}>
            <Select value={status} onValueChange={(v) => setStatus(v as ParameterStatus)}>
              <SelectTrigger size="sm" className="max-w-xs" aria-label="How the parameter is used">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(STATUS_LABELS) as ParameterStatus[]).map((s) => (
                  <SelectItem key={s} value={s}>
                    {STATUS_LABELS[s]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>

          <div>
            <span className="micro-label mb-1.5 block">Zones</span>
            {tagError && <p className="text-critical mb-2 text-[12px]">Can't load Timebase tags: {tagError}</p>}
            <div className="border-line overflow-hidden rounded-md border">
              <div className="bg-surface-muted text-ink-muted grid grid-cols-[1.1fr_110px_1.4fr_1.4fr_36px] gap-2 px-2.5 py-1.5 text-[11px] font-semibold uppercase">
                <span>Zone name</span>
                <span>ID</span>
                <span>Setpoint tag</span>
                <span>Actual tag</span>
                <span />
              </div>
              {zones.map((z, i) => (
                <div key={z.key} className="border-line-soft grid grid-cols-[1.1fr_110px_1.4fr_1.4fr_36px] items-start gap-2 border-t px-2.5 py-2">
                  <div>
                    <Input
                      value={z.name}
                      onChange={(e) =>
                        update(z.key, { name: e.target.value, ...(z.idEdited ? {} : { id: zoneIdFrom(e.target.value) }) })
                      }
                      placeholder="e.g. Vertical 7"
                      className="h-8 text-[13px]"
                      aria-label={`Zone ${i + 1} name`}
                    />
                    {err(`zones[${i}].name`) && <p className="text-critical mt-1 text-[11px]">{err(`zones[${i}].name`)}</p>}
                  </div>
                  <div>
                    <Input
                      value={z.id}
                      onChange={(e) => update(z.key, { id: e.target.value.toUpperCase(), idEdited: true })}
                      className="h-8 font-mono text-[12px]"
                      aria-label={`Zone ${i + 1} ID`}
                    />
                    {err(`zones[${i}].id`) && <p className="text-critical mt-1 text-[11px]">{err(`zones[${i}].id`)}</p>}
                  </div>
                  {(['setpoint', 'actual'] as const).map((kind) => (
                    <div key={kind} className="min-w-0">
                      <TagPicker
                        label={`Zone ${i + 1} ${kind} tag`}
                        value={z[kind]}
                        onChange={(tag) => update(z.key, { [kind]: tag })}
                        tags={tags}
                        parameterId={parameter.id}
                        invalid={Boolean(err(`zones[${i}].${kind}`))}
                      />
                      {err(`zones[${i}].${kind}`) && (
                        <p className="text-critical mt-1 text-[11px]">{err(`zones[${i}].${kind}`)}</p>
                      )}
                    </div>
                  ))}
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Remove zone ${z.name || i + 1}`}
                    onClick={() => setZones((list) => list.filter((x) => x.key !== z.key))}
                  >
                    <Trash2 className="size-4" aria-hidden />
                  </Button>
                </div>
              ))}
              {zones.length === 0 && <p className="text-ink-muted border-line-soft border-t px-3 py-3 text-[12px]">No zones yet.</p>}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  setZones((list) => [...list, { key: nextKey(), id: '', name: '', setpoint: null, actual: null, idEdited: false }])
                }
              >
                <Plus className="size-3.5" aria-hidden /> Add zone
              </Button>
              {parameter.candidateTags.length > 0 && (
                <span className="text-ink-soft text-[12px]">
                  Suggested from the machine tag list:{' '}
                  {parameter.candidateTags.map((t) => (
                    <code key={t} className="bg-surface-muted mr-1 rounded px-1 py-0.5 text-[11px]">
                      {t}
                    </code>
                  ))}
                </span>
              )}
            </div>
            {parameter.review && <p className="text-warning mt-2 text-[12px] leading-snug">Under review: {parameter.review}</p>}
          </div>

          <FormField label="Reason for the change" error={err('reason')} hint="Required. Kept with the new register version.">
            <Textarea
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Top 2 jaws now in use, confirmed on the HMI"
              className="text-[13px]"
              aria-label="Reason for the change"
            />
          </FormField>

          {problem && (problem.fieldErrors.length === 0 || problem.status === 409) && (
            <p className="text-critical flex items-center gap-1.5 text-[13px]">
              <XCircle className="size-4 shrink-0" aria-hidden /> {problem.message}
            </p>
          )}
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" size="sm" disabled={saving} onClick={() => void save()}>
            {saving ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Save className="size-4" aria-hidden />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
