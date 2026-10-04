import { CheckCircle2, Loader2, MailCheck, Save, Send, XCircle } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { SectionCard } from '@/components/shared/SectionCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ApiProblem } from '@/services/http'
import { notificationsApi } from '@/services/notificationsApi'
import type { Connections } from '@/types/configApi'
import type { NotificationsConnection, NotificationsForm } from '@/types/notificationsApi'

import { FormField, SecretInput } from './FormParts'

function toForm(c: NotificationsConnection): NotificationsForm {
  return {
    appUrl: c.appUrl,
    teamsUrl: '',
    clearTeams: false,
    smtpHost: c.email.host,
    smtpPort: c.email.port,
    smtpSecurity: c.email.security,
    smtpUsername: c.email.username,
    smtpPassword: '',
    clearSmtpPassword: false,
    emailSender: c.email.sender,
    reason: '',
  }
}

/**
 * Where the notifier sends (ADR-0023): Teams through a Power Automate flow, email through the
 * plant's SMTP relay. The flow URL carries its signature and the relay password is a secret:
 * both are write-only. Until IT gives the real ones (O-05), tools/notify-sink stands in.
 */
export function NotificationsConnectionCard({
  connection,
  onSaved,
}: {
  connection: NotificationsConnection
  onSaved: (c: Connections) => void
}) {
  const [form, setForm] = useState<NotificationsForm>(() => toForm(connection))
  const [busy, setBusy] = useState<'test' | 'save' | null>(null)
  const [problem, setProblem] = useState<ApiProblem | null>(null)
  const [check, setCheck] = useState<{ ok: boolean; response: string } | null>(null)
  const set = (patch: Partial<NotificationsForm>) => setForm((f) => ({ ...f, ...patch }))
  const err = (field: string) => problem?.forField(field)

  const run = async (kind: 'test' | 'save') => {
    setBusy(kind)
    setProblem(null)
    try {
      if (kind === 'test') {
        setCheck(null)
        setCheck(await notificationsApi.testEmail(form))
      } else {
        const saved = await notificationsApi.saveConnection(form)
        onSaved(saved)
        setForm(toForm(saved.notifications))
        toast.success('Notification channels saved', {
          description: [saved.notifications.teams.configured && 'Teams', saved.notifications.email.configured && 'email']
            .filter(Boolean)
            .join(' and ') || 'No channel is set up',
        })
      }
    } catch (caught) {
      setProblem(caught instanceof ApiProblem ? caught : new ApiProblem(0, { detail: String(caught) }))
    } finally {
      setBusy(null)
    }
  }

  return (
    <SectionCard
      title="Notifications · Teams and email"
      description="Where the notifier sends alerts. Who gets which ones is on the Notifications tab."
      icon={Send}
      actions={
        <span className="flex gap-1.5">
          <Badge variant={connection.teams.configured ? 'normal' : 'neutral'}>Teams {connection.teams.configured ? 'set' : 'not set'}</Badge>
          <Badge variant={connection.email.configured ? 'normal' : 'neutral'}>Email {connection.email.configured ? 'set' : 'not set'}</Badge>
        </span>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          void run('save')
        }}
      >
        <FormField label="Centerline's address, for the links in messages" error={err('appUrl')} hint="e.g. https://centerline.plant.local">
          <Input value={form.appUrl} onChange={(e) => set({ appUrl: e.target.value })} className="h-8 font-mono text-[12px]" aria-label="Centerline address" />
        </FormField>

        <fieldset className="border-line flex flex-col gap-3 rounded-md border px-3 pt-2 pb-3">
          <legend className="micro-label px-1">Teams · Power Automate flow</legend>
          <FormField
            label="The flow's HTTP POST URL"
            error={err('teamsUrl')}
            hint={
              connection.teams.configured
                ? `Saved, for ${connection.teams.where}. It carries the flow's signature, so it's never shown again.`
                : 'From IT: the "When a HTTP request is received" trigger. Stored on the server, never shown again (O-05).'
            }
          >
            <SecretInput
              key={`teams-${connection.teams.configured}`} // shows "Saved" again once it's saved
              label="Flow URL"
              isSet={connection.teams.configured}
              value={form.teamsUrl}
              onChange={(teamsUrl) => set({ teamsUrl, clearTeams: false })}
              onRemove={() => set({ teamsUrl: '', clearTeams: true })}
              removed={form.clearTeams}
              placeholder="https://…logic.azure.com/workflows/…"
            />
          </FormField>
        </fieldset>

        <fieldset className="border-line flex flex-col gap-3 rounded-md border px-3 pt-2 pb-3">
          <legend className="micro-label px-1">Email · the plant's SMTP relay</legend>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_100px_150px]">
            <FormField label="Relay host" error={err('smtpHost')}>
              <Input value={form.smtpHost} onChange={(e) => set({ smtpHost: e.target.value })} placeholder="smtp-relay.plant.local"
                     className="h-8 font-mono text-[12px]" aria-label="SMTP relay host" />
            </FormField>
            <FormField label="Port" error={err('smtpPort')}>
              <Input type="number" min={1} max={65535} value={form.smtpPort} onChange={(e) => set({ smtpPort: Number(e.target.value) })}
                     className="h-8 text-[13px]" aria-label="SMTP port" />
            </FormField>
            <FormField label="Security">
              <Select value={form.smtpSecurity} onValueChange={(v) => set({ smtpSecurity: v as NotificationsForm['smtpSecurity'] })}>
                <SelectTrigger size="sm" aria-label="SMTP security">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  <SelectItem value="starttls">STARTTLS</SelectItem>
                  <SelectItem value="tls">TLS</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <FormField label="From address" error={err('emailSender')}>
              <Input value={form.emailSender} onChange={(e) => set({ emailSender: e.target.value })} placeholder="centerline@plant.local"
                     className="h-8 text-[13px]" aria-label="From address" />
            </FormField>
            <FormField label="User name" hint="Empty if the relay takes mail by address">
              <Input value={form.smtpUsername} onChange={(e) => set({ smtpUsername: e.target.value })} className="h-8 text-[13px]"
                     aria-label="SMTP user name" />
            </FormField>
            <FormField label="Password" error={err('smtpPassword')}>
              <SecretInput
                key={`smtp-${connection.email.passwordSet}`}
                label="SMTP password"
                isSet={connection.email.passwordSet}
                value={form.smtpPassword}
                onChange={(smtpPassword) => set({ smtpPassword, clearSmtpPassword: false })}
                onRemove={() => set({ smtpPassword: '', clearSmtpPassword: true })}
                removed={form.clearSmtpPassword}
                placeholder="Password"
              />
            </FormField>
          </div>
        </fieldset>

        <FormField label="Reason for the change" hint="Optional; kept in the change history">
          <Input value={form.reason} onChange={(e) => set({ reason: e.target.value })} placeholder="e.g. Relay details from IT"
                 className="h-8 text-[13px]" aria-label="Reason for the change" />
        </FormField>

        {problem && problem.fieldErrors.length === 0 && (
          <p className="text-critical flex items-center gap-1.5 text-[13px]">
            <XCircle className="size-4" aria-hidden /> {problem.message}
          </p>
        )}

        <div className="border-line flex flex-wrap items-center justify-end gap-2 border-t pt-3">
          <Button type="button" variant="outline" size="sm" disabled={busy !== null || !form.smtpHost.trim()} onClick={() => void run('test')}>
            {busy === 'test' ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <MailCheck className="size-4" aria-hidden />}
            Test the relay
          </Button>
          <Button type="submit" size="sm" disabled={busy !== null}>
            {busy === 'save' ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Save className="size-4" aria-hidden />}
            Save
          </Button>
        </div>
      </form>

      {check && (
        <div
          className={
            check.ok
              ? 'border-line mt-4 rounded-md border px-3 py-2.5 text-[13px]'
              : 'border-critical-border bg-critical-surface mt-4 rounded-md border px-3 py-2.5 text-[13px]'
          }
          role="status"
        >
          <p className={check.ok ? 'text-normal flex items-center gap-1.5 font-medium' : 'text-critical flex items-center gap-1.5 font-medium'}>
            {check.ok ? <CheckCircle2 className="size-4" aria-hidden /> : <XCircle className="size-4" aria-hidden />}
            {check.ok ? 'The relay answered, and nothing was sent' : 'The relay didn’t answer'}
          </p>
          <p className="text-ink mt-1 font-mono text-[12px]">{check.response}</p>
          <p className="text-ink-soft mt-1 text-[12px]">To try a whole message, send a TEST from the Notifications page.</p>
        </div>
      )}
    </SectionCard>
  )
}
