import { CheckCircle2, Database, Loader2, PlugZap, Save, TriangleAlert, XCircle } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { SectionCard } from '@/components/shared/SectionCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ApiProblem } from '@/services/http'
import { configApi } from '@/services/configApi'
import type { Connections, HistorianAuth, HistorianCheck, HistorianConnection, HistorianForm } from '@/types/configApi'
import { formatDuration } from '@/utils/manilaTime'

import { CheckRow, FormField, SecretInput } from './FormParts'

function toForm(c: HistorianConnection): HistorianForm {
  return {
    baseUrl: c.baseUrl,
    dataset: c.dataset,
    timeoutS: c.timeoutS,
    verifyTls: c.verifyTls,
    authType: c.authType,
    username: c.username,
    token: '',
    password: '',
    reason: '',
  }
}

/** History (ADR-0008): the Timebase server Analytics reads. Only GET requests are ever sent. */
export function HistorianConnectionCard({
  connection,
  onSaved,
}: {
  connection: HistorianConnection
  onSaved: (c: Connections) => void
}) {
  const [form, setForm] = useState<HistorianForm>(() => toForm(connection))
  const [busy, setBusy] = useState<'test' | 'save' | null>(null)
  const [problem, setProblem] = useState<ApiProblem | null>(null)
  const [check, setCheck] = useState<HistorianCheck | null>(null)
  const set = (patch: Partial<HistorianForm>) => setForm((f) => ({ ...f, ...patch }))
  const err = (field: string) => problem?.forField(field)

  const run = async (kind: 'test' | 'save') => {
    setBusy(kind)
    setProblem(null)
    try {
      if (kind === 'test') {
        setCheck(null)
        setCheck(await configApi.testHistorian(form))
      } else {
        const saved = await configApi.saveHistorian(form)
        onSaved(saved)
        setForm(toForm(saved.historian))
        toast.success('Historian connection saved', { description: `${saved.historian.baseUrl} · ${saved.historian.dataset}` })
      }
    } catch (caught) {
      setProblem(caught instanceof ApiProblem ? caught : new ApiProblem(0, { detail: String(caught) }))
    } finally {
      setBusy(null)
    }
  }

  return (
    <SectionCard
      title="History · Timebase"
      description="Where Analytics reads history. Centerline only reads from it."
      icon={Database}
      actions={<Badge variant="neutral">From the {connection.source}</Badge>}
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          void run('save')
        }}
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_180px]">
          <FormField label="Server URL" error={err('baseUrl')} hint="e.g. http://10.156.116.179:4516">
            <Input
              value={form.baseUrl}
              onChange={(e) => set({ baseUrl: e.target.value })}
              className="h-8 font-mono text-[12px]"
              aria-label="Timebase server URL"
            />
          </FormField>
          <FormField label="Dataset" error={err('dataset')}>
            <Input value={form.dataset} onChange={(e) => set({ dataset: e.target.value })} className="h-8 text-[13px]" aria-label="Dataset" />
          </FormField>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[180px_1fr]">
          <FormField label="Sign-in">
            <Select value={form.authType} onValueChange={(v) => set({ authType: v as HistorianAuth })}>
              <SelectTrigger size="sm" aria-label="Sign-in method">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None</SelectItem>
                <SelectItem value="bearer">Bearer token</SelectItem>
                <SelectItem value="basic">User name + password</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
          {form.authType === 'bearer' && (
            <FormField label="Token" error={err('token')} hint="Stored on the server, never shown again">
              <SecretInput
                label="Bearer token"
                isSet={connection.tokenSet}
                value={form.token}
                onChange={(token) => set({ token })}
                placeholder="Paste the token"
              />
            </FormField>
          )}
          {form.authType === 'basic' && (
            <div className="grid grid-cols-2 gap-3">
              <FormField label="User name" error={err('username')}>
                <Input value={form.username} onChange={(e) => set({ username: e.target.value })} className="h-8 text-[13px]" aria-label="Timebase user name" />
              </FormField>
              <FormField label="Password" error={err('password')}>
                <SecretInput
                  label="Timebase password"
                  isSet={connection.passwordSet}
                  value={form.password}
                  onChange={(password) => set({ password })}
                  placeholder="Password"
                />
              </FormField>
            </div>
          )}
          {form.authType === 'none' && (
            <p className="text-ink-soft self-end pb-1 text-[12px]">
              The plant server answered reads without a token on 2026-09-29. Ask the Timebase admin to enforce one (M7).
            </p>
          )}
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[140px_1fr]">
          <FormField label="Timeout (s)" error={err('timeoutS')}>
            <Input
              type="number"
              min={5}
              max={300}
              value={form.timeoutS}
              onChange={(e) => set({ timeoutS: Number(e.target.value) })}
              className="h-8 text-[13px]"
              aria-label="Timeout seconds"
            />
          </FormField>
          <div className="self-end pb-1">
            <CheckRow
              checked={form.verifyTls}
              onChange={(verifyTls) => set({ verifyTls })}
              disabled={!form.baseUrl.startsWith('https')}
              label="Verify the certificate"
              description="For https:// only"
            />
          </div>
        </div>

        <FormField label="Reason for the change" hint="Optional; kept in the change history">
          <Input
            value={form.reason}
            onChange={(e) => set({ reason: e.target.value })}
            placeholder="e.g. Token from the Timebase admin"
            className="h-8 text-[13px]"
            aria-label="Reason for the change"
          />
        </FormField>

        {problem && problem.fieldErrors.length === 0 && (
          <p className="text-critical flex items-center gap-1.5 text-[13px]">
            <XCircle className="size-4" aria-hidden /> {problem.message}
          </p>
        )}

        <div className="border-line flex flex-wrap items-center justify-end gap-2 border-t pt-3">
          <Button type="button" variant="outline" size="sm" disabled={busy !== null} onClick={() => void run('test')}>
            {busy === 'test' ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <PlugZap className="size-4" aria-hidden />}
            Test connection
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
          {check.ok ? (
            <>
              <p className="text-normal flex items-center gap-1.5 font-medium">
                <CheckCircle2 className="size-4" aria-hidden /> Connected in {check.latencyMs} ms
              </p>
              <p className="text-ink mt-1">
                Dataset <b>{form.dataset}</b> found · <b>{check.tagsUnderNamespace}</b> tags under the machine
              </p>
              {check.clockOffsetS !== null && check.clockOffsetS !== undefined && Math.abs(check.clockOffsetS) > 30 && (
                <p className="text-ink mt-1 flex items-start gap-1.5 text-[12px]">
                  <TriangleAlert className="text-warning mt-0.5 size-3.5 shrink-0" aria-hidden />
                  The server clock is {formatDuration(check.clockOffsetS)} {check.clockOffsetS < 0 ? 'behind' : 'ahead of'} this
                  one (O-18).
                </p>
              )}
            </>
          ) : (
            <>
              <p className="text-critical flex items-center gap-1.5 font-medium">
                <XCircle className="size-4" aria-hidden /> Not connected
              </p>
              <p className="text-ink mt-1">{check.error}</p>
              {check.datasets && check.datasets.length > 0 && (
                <p className="text-ink-soft mt-1 text-[12px]">Datasets on this server: {check.datasets.join(', ')}</p>
              )}
            </>
          )}
        </div>
      )}
    </SectionCard>
  )
}
