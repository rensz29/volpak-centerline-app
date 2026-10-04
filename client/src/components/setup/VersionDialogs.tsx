import { Loader2, TriangleAlert, XCircle } from 'lucide-react'
import { useState, type ReactNode } from 'react'

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
import { Textarea } from '@/components/ui/textarea'
import type { ApiProblem } from '@/services/http'
import { formatManilaFull, fromManilaInput, toUtcIso } from '@/utils/manilaTime'

import { FormField } from './FormParts'
import { asProblem, nextHourInput } from './versionUtils'

/**
 * Dialogs for numbered versions that take effect through activations: the rules
 * (ADR-0012) and the tag mappings (ADR-0013).
 */

export function ProblemLine({ problem }: { problem: ApiProblem | null }) {
  if (!problem || problem.fieldErrors.length > 0) return null
  return (
    <p className="text-critical flex items-center gap-1.5 text-[13px]">
      <XCircle className="size-4 shrink-0" aria-hidden /> {problem.message}
    </p>
  )
}

/** Activate a version now or at a set Manila time. Activating an older version is a rollback. */
export function ActivateDialog({
  label,
  number,
  rollback,
  activeNumber,
  scheduled,
  details,
  blocked,
  placeholder = 'e.g. Confirmed with process engineering',
  onActivate,
  onClose,
}: {
  label: string
  number: number
  rollback: boolean
  activeNumber: number | null
  scheduled: { number: number; at: string }[]
  details?: ReactNode
  /** Why the version can't be activated, if it can't. */
  blocked?: string | null
  placeholder?: string
  onActivate: (at: string | null, reason: string) => Promise<void>
  onClose: () => void
}) {
  const [when, setWhen] = useState<'now' | 'at'>('now')
  const [at, setAt] = useState(nextHourInput)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<ApiProblem | null>(null)
  const later = scheduled.filter((s) => s.number !== number)

  const submit = async () => {
    setBusy(true)
    setProblem(null)
    try {
      const epoch = when === 'at' ? fromManilaInput(at) : null
      await onActivate(epoch === null ? null : toUtcIso(epoch), reason)
    } catch (caught) {
      setProblem(asProblem(caught))
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>{rollback ? `Roll back to ${label} v${number}` : `Activate ${label} v${number}`}</DialogTitle>
          <DialogDescription>
            {activeNumber
              ? `${label} v${activeNumber} is in effect now. Events already open keep the version they started under.`
              : `No ${label.toLowerCase()} version is in effect yet.`}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <fieldset className="flex flex-col gap-2 text-[13px]">
            <legend className="micro-label mb-1.5">When</legend>
            <label className="flex items-center gap-2">
              <input type="radio" name="when" checked={when === 'now'} onChange={() => setWhen('now')} /> Now
            </label>
            <label className="flex flex-wrap items-center gap-2">
              <input type="radio" name="when" checked={when === 'at'} onChange={() => setWhen('at')} /> At
              <Input
                type="datetime-local"
                value={at}
                onChange={(e) => {
                  setAt(e.target.value)
                  setWhen('at')
                }}
                className="h-8 w-auto text-[13px]"
                aria-label="Activation time, Manila"
              />
              <span className="text-ink-muted text-[12px]">Manila time, e.g. a shift start</span>
            </label>
            {problem?.forField('at') && <p className="text-critical text-[12px]">{problem.forField('at')}</p>}
          </fieldset>

          {details}
          {blocked && (
            <p className="text-critical flex items-start gap-1.5 text-[12px] leading-snug">
              <XCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {blocked}
            </p>
          )}
          {later.length > 0 && (
            <p className="text-warning flex items-start gap-1.5 text-[12px] leading-snug">
              <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {later.map((s) => `${label} v${s.number} is scheduled for ${formatManilaFull(Date.parse(s.at))}`).join('; ')}. That
              will still take over then unless you cancel it.
            </p>
          )}

          <FormField label="Reason" error={problem?.forField('reason')} hint="Required. Kept in the change history.">
            <Textarea
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={placeholder}
              className="text-[13px]"
              aria-label="Reason"
            />
          </FormField>
          {problem && problem.fieldErrors.some((e) => e.field !== 'at' && e.field !== 'reason') && (
            <ul className="text-critical list-disc pl-5 text-[12px]">
              {problem.fieldErrors
                .filter((e) => e.field !== 'at' && e.field !== 'reason')
                .map((e) => (
                  <li key={e.field + e.message}>{e.message}</li>
                ))}
            </ul>
          )}
          <ProblemLine problem={problem} />
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" size="sm" disabled={busy || Boolean(blocked)} onClick={() => void submit()}>
            {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
            {when === 'now' ? (rollback ? 'Roll back now' : 'Activate now') : 'Schedule'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Asks for a reason, then runs the action (cancel a schedule, remove a SKU). */
export function ReasonDialog({
  title,
  description,
  confirm,
  destructive = false,
  required = true,
  onClose,
  onConfirm,
}: {
  title: string
  description: string
  confirm: string
  destructive?: boolean
  required?: boolean
  onClose: () => void
  onConfirm: (reason: string) => Promise<void>
}) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<ApiProblem | null>(null)

  const submit = async () => {
    setBusy(true)
    setProblem(null)
    try {
      await onConfirm(reason)
    } catch (caught) {
      setProblem(asProblem(caught))
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-3">
          <FormField
            label="Reason"
            error={problem?.forField('reason')}
            hint={required ? 'Required. Kept in the change history.' : 'Optional; kept in the change history'}
          >
            <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} className="text-[13px]" aria-label="Reason" />
          </FormField>
          <ProblemLine problem={problem} />
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Back
          </Button>
          <Button type="button" size="sm" variant={destructive ? 'destructive' : 'default'} disabled={busy} onClick={() => void submit()}>
            {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
            {confirm}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
