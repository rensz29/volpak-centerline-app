import { Loader2, Wrench } from 'lucide-react'
import { useState } from 'react'

import { windowScope } from '@/components/live/controlModel'
import { CheckRow, FormField } from '@/components/setup/FormParts'
import { ProblemLine } from '@/components/setup/VersionDialogs'
import { asProblem } from '@/components/setup/versionUtils'
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
import { monitoringApi } from '@/services/monitoringApi'
import type { ApiProblem } from '@/services/http'
import type { LiveParameter, MaintenanceWindow } from '@/types/monitoringApi'
import { cn } from '@/utils/cn'
import { fromManilaInput, toManilaInput } from '@/utils/manilaTime'

const HOUR = 3600_000
const toIso = (manila: string) => {
  const ms = fromManilaInput(manila)
  return ms === null ? null : new Date(ms).toISOString()
}

/** An Administrator opens a maintenance window for the line or chosen zones, now or later (MNT-01). */
export function OpenWindowDialog({ parameters, onClose, onDone }: {
  parameters: LiveParameter[]
  onClose: () => void
  onDone: (w: MaintenanceWindow) => void
}) {
  const [scope, setScope] = useState<'line' | 'zones'>('zones')
  const [channels, setChannels] = useState<string[]>([])
  const [reason, setReason] = useState('')
  const [later, setLater] = useState(false)
  const [start, setStart] = useState(() => toManilaInput(Date.now() + HOUR))
  const [end, setEnd] = useState(() => toManilaInput(Date.now() + HOUR))
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<ApiProblem | null>(null)

  const toggle = (ch: string, on: boolean) => setChannels((c) => (on ? [...c, ch] : c.filter((x) => x !== ch)))
  /** A quick planned end: this long after the start (now, unless it starts later). */
  function lasting(hours: number) {
    const from = (later ? fromManilaInput(start) : null) ?? new Date().getTime()
    setEnd(toManilaInput(from + hours * HOUR))
  }

  const submit = async () => {
    setBusy(true)
    setProblem(null)
    try {
      const endIso = toIso(end)
      if (!endIso) throw new Error('Enter the planned end')
      onDone(await monitoringApi.openWindow({ scope, channels: scope === 'zones' ? channels : [], reason,
                                              start: later ? toIso(start) : null, end: endIso }))
    } catch (caught) {
      setProblem(asProblem(caught))
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wrench className="size-5" aria-hidden /> Open a maintenance window
          </DialogTitle>
          <DialogDescription>
            While it's in force nothing is judged there: delays and repeats wait, open events stay open. Past its planned end it
            stays in force, overdue, until you end it.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <FormField label="Covers" error={problem?.forField('channels')}>
            <div className="flex flex-col gap-2">
              <CheckRow checked={scope === 'line'} onChange={(on) => setScope(on ? 'line' : 'zones')} label="The whole line"
                        description="e.g. a network or broker change: all judging pauses, like a lost connection" />
              <CheckRow checked={scope === 'zones'} onChange={(on) => setScope(on ? 'zones' : 'line')} label="Chosen zones"
                        description="The zones being worked on; the rest of the line stays judged" />
            </div>
          </FormField>
          {scope === 'zones' && (
            <div className="border-line max-h-[220px] overflow-y-auto rounded-lg border px-3 py-2">
              {parameters.map((p) => (
                <div key={p.id} className="py-1">
                  <p className="micro-label mb-1">{p.name}</p>
                  <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                    {p.zones.map((z) => (
                      <CheckRow key={z.channel} checked={channels.includes(z.channel)} onChange={(on) => toggle(z.channel, on)} label={z.name} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
          <FormField label="Reason" error={problem?.forField('reason')}>
            <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Replacing the front top heater" />
          </FormField>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField label="Starts" error={problem?.forField('start')}>
              <div className="flex flex-col gap-2">
                <CheckRow checked={!later} onChange={(on) => setLater(!on)} label="Now" />
                <CheckRow checked={later} onChange={setLater} label="At (Manila time)" />
                {later && <Input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />}
              </div>
            </FormField>
            <FormField label="Planned end (Manila time)" error={problem?.forField('end')}>
              <div className="flex flex-col gap-2">
                <Input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} />
                <div className="flex flex-wrap gap-1.5">
                  {[0.5, 1, 2, 4].map((h) => (
                    <Button key={h} type="button" variant="outline" size="sm" className="h-7 px-2 text-[12px]" onClick={() => lasting(h)}>
                      {h < 1 ? '30 min' : `${h} h`}
                    </Button>
                  ))}
                </div>
              </div>
            </FormField>
          </div>
          <ProblemLine problem={problem} />
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" size="sm" disabled={busy || !reason.trim() || (scope === 'zones' && channels.length === 0)}
                  onClick={() => void submit()}>
            {busy && <Loader2 className="size-4 animate-spin" aria-hidden />} {later ? 'Schedule' : 'Start now'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Move the planned end, or end the window now (a window that hasn't started is cancelled). */
export function WindowActionDialog({ window: w, action, onClose, onDone }: {
  window: MaintenanceWindow
  action: 'extend' | 'end'
  onClose: () => void
  onDone: () => void
}) {
  const [end, setEnd] = useState(() => toManilaInput(Math.max(Date.parse(w.plannedEnd), Date.now()) + HOUR / 2))
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<ApiProblem | null>(null)
  const cancelling = w.status === 'scheduled'

  const submit = async () => {
    setBusy(true)
    setProblem(null)
    try {
      if (action === 'extend') {
        const endIso = toIso(end)
        if (!endIso) throw new Error('Enter the new planned end')
        await monitoringApi.extendWindow(w.id, endIso, reason)
      } else {
        await monitoringApi.endWindow(w.id, reason)
      }
      onDone()
    } catch (caught) {
      setProblem(asProblem(caught))
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle>{action === 'extend' ? 'Move the planned end' : cancelling ? 'Cancel this window' : 'End maintenance now'}</DialogTitle>
          <DialogDescription>
            “{w.reason}” on {windowScope(w)}.{' '}
            {action === 'end' && !cancelling && 'Judging resumes on fresh values; delays and repeats start from zero (MNT-02).'}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-3">
          {action === 'extend' && (
            <FormField label="New planned end (Manila time)" error={problem?.forField('end')}>
              <Input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} />
            </FormField>
          )}
          <FormField label="Reason (optional)">
            <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)}
                      placeholder={action === 'extend' ? 'e.g. The spare part came late' : 'e.g. Work done and checked'} />
          </FormField>
          <ProblemLine problem={problem} />
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Back
          </Button>
          <Button type="button" size="sm" disabled={busy} className={cn(action === 'end' && 'bg-critical-solid hover:bg-critical-solid/90')}
                  onClick={() => void submit()}>
            {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
            {action === 'extend' ? 'Move the end' : cancelling ? 'Cancel window' : 'End now'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
