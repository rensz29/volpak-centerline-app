import { Loader2, Power, PowerOff, Wrench } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { CheckRow, FormField } from '@/components/setup/FormParts'
import { SectionCard } from '@/components/shared/SectionCard'
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
import { Textarea } from '@/components/ui/textarea'
import { ROUTES } from '@/routes/navigation'
import { monitoringApi } from '@/services/monitoringApi'
import type { LiveParameter, LiveZone, MaintenanceWindow, SwitchedOffZone } from '@/types/monitoringApi'
import { cn } from '@/utils/cn'
import { formatManilaShort } from '@/utils/manilaTime'

import { windowScope, windowTiming, windowTone } from './controlModel'
import { TONE } from './liveModel'

/**
 * Monitoring control on the live page (ADR-0017): the maintenance windows in force or coming,
 * the zones switched off, and a Manager switching a zone off or on again.
 */

export function MaintenanceBar({ windows, now, canManage }: { windows: MaintenanceWindow[]; now: number; canManage: boolean }) {
  if (windows.length === 0) return null
  return (
    <div className="flex flex-col gap-2">
      {windows.map((w) => {
        const title = w.status === 'scheduled' ? 'Maintenance scheduled' : w.status === 'overdue' ? 'Maintenance overdue' : 'Maintenance'
        return (
          <div key={w.id} className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-4 py-2 text-[13px]', TONE[windowTone(w, now)].badge)}>
            <Wrench className="size-4 shrink-0" aria-hidden />
            <span className="text-ink font-semibold">
              {title} on {windowScope(w)}
            </span>
            <span className="text-ink-soft">
              “{w.reason}”, {windowTiming(w, now)}
            </span>
            {w.status !== 'scheduled' && (
              <span className="text-ink-muted text-[12px]">
                {w.scope === 'line' ? 'Nothing is judged' : "These zones aren't judged"}; open events stay open.
              </span>
            )}
            {canManage && (
              <Link to={ROUTES.maintenance} className="text-brand ml-auto text-[12px] font-medium hover:underline">
                Manage
              </Link>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** Every zone switched off, prominently, so none is forgotten; a Manager switches it on again. */
export function SwitchedOffCard({ zones, canSwitch, onChanged }: { zones: SwitchedOffZone[]; canSwitch: boolean; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  if (zones.length === 0) return null
  const switchOn = async (z: SwitchedOffZone) => {
    setBusy(z.channel)
    try {
      await monitoringApi.switchZones([z.channel], true, '')
      toast.success(`Monitoring switched on for ${z.zoneName}`, { description: "It's judged again on its next fresh values." })
      onChanged()
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(null)
    }
  }
  return (
    <SectionCard title="Switched off" icon={PowerOff} flush className="border-warning-border"
                 description={`${zones.length} zone${zones.length === 1 ? '' : 's'} not monitored: switched off by a Manager (MON-01)`}>
      <table className="w-full text-[13px]">
        <tbody>
          {zones.map((z) => (
            <tr key={z.channel} className="border-line-soft border-b last:border-b-0">
              <td className="px-5 py-2">
                <span className="text-ink font-medium">{z.zoneName}</span>
                <span className="text-ink-muted ml-2 text-[12px]">{z.parameterName}</span>
              </td>
              <td className="text-ink-soft px-3 py-2 text-[12px] whitespace-nowrap">
                since {formatManilaShort(Date.parse(z.since))} by {z.by}
              </td>
              <td className="text-ink px-3 py-2">{z.reason}</td>
              <td className="px-3 py-2 text-right">
                {canSwitch && (
                  <Button type="button" variant="outline" size="sm" disabled={busy !== null} onClick={() => void switchOn(z)}>
                    {busy === z.channel ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Power className="size-3.5" aria-hidden />}
                    Switch on
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </SectionCard>
  )
}

/** A Manager switches monitoring off for a zone, or all of its parameter's zones, with a reason (MON-01). */
export function SwitchOffDialog({ zone, parameter, onClose, onDone }: {
  zone: LiveZone
  parameter: LiveParameter
  onClose: () => void
  onDone: () => void
}) {
  const [all, setAll] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const channels = all ? parameter.zones.filter((z) => !z.control || z.control.state !== 'off').map((z) => z.channel) : [zone.channel]

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await monitoringApi.switchZones(channels, false, reason)
      toast.success(`Monitoring switched off: ${r.changed.length} zone${r.changed.length === 1 ? '' : 's'}`)
      onDone()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Switch monitoring off</DialogTitle>
          <DialogDescription>
            {all ? `All zones of ${parameter.name}` : `${zone.name} (${parameter.name})`} stop being judged. An open event there closes as
            “Monitoring disabled”, with no recovery notice; notices already sent stay on record.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          {parameter.zones.length > 1 && (
            <CheckRow checked={all} onChange={setAll} label={`All zones of ${parameter.name} (${parameter.zones.length})`}
                      description="Instead of this zone only" />
          )}
          <FormField label="Reason" hint="Kept in the history, and shown on the page until it's switched on again">
            <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Thermocouple broken, replacement ordered" />
          </FormField>
          {error && <p className="text-critical text-[13px]">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" size="sm" disabled={busy || !reason.trim() || channels.length === 0} onClick={() => void submit()}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <PowerOff className="size-4" aria-hidden />} Switch off
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
