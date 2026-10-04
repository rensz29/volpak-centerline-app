import { CheckCircle2, Loader2, PlugZap, Radio, Save, TriangleAlert, Upload, XCircle } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { SectionCard } from '@/components/shared/SectionCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { ApiProblem } from '@/services/http'
import { configApi } from '@/services/configApi'
import type { Connections, MqttCheck, MqttConnection, MqttForm } from '@/types/configApi'

import { CheckRow, FormField, SecretInput } from './FormParts'

const TEST_SECONDS = 10

function toForm(c: MqttConnection): MqttForm {
  return {
    host: c.host,
    port: c.port,
    protocol: c.protocol,
    tlsEnabled: c.tlsEnabled,
    verifyHostname: c.verifyHostname,
    caPem: '',
    clearCa: false,
    username: c.username,
    password: '',
    clearPassword: false,
    clientId: c.clientId,
    keepaliveS: c.keepaliveS,
    subscriptions: c.subscriptions,
    freshnessS: c.freshnessS,
    reason: '',
  }
}

/** Live data (ADR-0006): the plant broker the monitoring engine subscribes to. Read-only by design. */
export function MqttConnectionCard({
  connection,
  onSaved,
}: {
  connection: MqttConnection
  onSaved: (c: Connections) => void
}) {
  const [form, setForm] = useState<MqttForm>(() => toForm(connection))
  const [caName, setCaName] = useState<string | null>(null)
  const [busy, setBusy] = useState<'test' | 'save' | null>(null)
  const [problem, setProblem] = useState<ApiProblem | null>(null)
  const [check, setCheck] = useState<MqttCheck | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const set = (patch: Partial<MqttForm>) => setForm((f) => ({ ...f, ...patch }))
  const err = (field: string) => problem?.forField(field)

  const run = async (kind: 'test' | 'save') => {
    setBusy(kind)
    setProblem(null)
    try {
      if (kind === 'test') {
        setCheck(null)
        setCheck(await configApi.testMqtt(form, TEST_SECONDS))
      } else {
        const saved = await configApi.saveMqtt(form)
        onSaved(saved)
        setForm(toForm(saved.mqtt))
        setCaName(null)
        toast.success('MQTT connection saved', { description: `${saved.mqtt.host}:${saved.mqtt.port}` })
      }
    } catch (caught) {
      setProblem(caught instanceof ApiProblem ? caught : new ApiProblem(0, { detail: String(caught) }))
    } finally {
      setBusy(null)
    }
  }

  return (
    <SectionCard
      title="Live data · MQTT broker"
      description="The plant broker the monitoring engine subscribes to. Centerline never publishes to it."
      icon={Radio}
      actions={
        connection.configured ? (
          <Badge variant="normal">Saved · {connection.host}:{connection.port}</Badge>
        ) : (
          <Badge variant="neutral">Not set up yet</Badge>
        )
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          void run('save')
        }}
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_110px_140px]">
          <FormField label="Host" error={err('host')} hint="Host name or IP address, without mqtt://">
            <Input
              value={form.host}
              onChange={(e) => set({ host: e.target.value })}
              placeholder="broker.plant.local"
              className="h-8 text-[13px]"
              aria-label="Broker host"
            />
          </FormField>
          <FormField label="Port" error={err('port')}>
            <Input
              type="number"
              min={1}
              max={65535}
              value={form.port}
              onChange={(e) => set({ port: Number(e.target.value) })}
              className="h-8 text-[13px]"
              aria-label="Broker port"
            />
          </FormField>
          <FormField label="Protocol">
            <Select value={form.protocol} onValueChange={(v) => set({ protocol: v as MqttForm['protocol'] })}>
              <SelectTrigger size="sm" aria-label="MQTT protocol version">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="5">MQTT 5</SelectItem>
                <SelectItem value="3.1.1">MQTT 3.1.1</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
        </div>

        <div className="border-line grid grid-cols-1 gap-3 rounded-md border p-3 sm:grid-cols-2">
          <CheckRow
            checked={form.tlsEnabled}
            onChange={(tlsEnabled) =>
              set({
                tlsEnabled,
                port: tlsEnabled && form.port === 1883 ? 8883 : !tlsEnabled && form.port === 8883 ? 1883 : form.port,
              })
            }
            label="Use TLS (recommended)"
            description="Encrypts the password and values on the network (control M1)"
          />
          <CheckRow
            checked={form.verifyHostname}
            onChange={(verifyHostname) => set({ verifyHostname })}
            disabled={!form.tlsEnabled}
            label="Verify the broker's host name"
            description="Keep on unless the certificate doesn't name this host"
          />
          <FormField
            label="CA certificate"
            className="sm:col-span-2"
            error={err('caPem')}
            hint="The plant CA that signed the broker's certificate. Without one, the system's CAs are used."
          >
            <div className="flex flex-wrap items-center gap-2">
              {caName ? (
                <Badge variant="default">{caName} · saved on Save</Badge>
              ) : form.clearCa ? (
                <Badge variant="warning">Removed on Save</Badge>
              ) : connection.caSet ? (
                <Badge variant="normal">Saved</Badge>
              ) : (
                <Badge variant="neutral">None</Badge>
              )}
              <input
                ref={file}
                type="file"
                accept=".pem,.crt,.cer"
                className="hidden"
                onChange={async (e) => {
                  const f = e.target.files?.[0]
                  if (!f) return
                  set({ caPem: await f.text(), clearCa: false })
                  setCaName(f.name)
                  e.target.value = ''
                }}
              />
              <Button type="button" variant="outline" size="sm" disabled={!form.tlsEnabled} onClick={() => file.current?.click()}>
                <Upload className="size-3.5" aria-hidden />
                Upload .pem
              </Button>
              {(connection.caSet || caName) && !form.clearCa && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    set({ caPem: '', clearCa: connection.caSet })
                    setCaName(null)
                  }}
                >
                  Remove
                </Button>
              )}
            </div>
          </FormField>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField label="User name" hint="A dedicated, subscribe-only Centerline account (M2, M3)">
            <Input
              value={form.username}
              onChange={(e) => set({ username: e.target.value })}
              placeholder="centerline"
              autoComplete="off"
              className="h-8 text-[13px]"
              aria-label="Broker user name"
            />
          </FormField>
          <FormField label="Password" hint="Stored on the server, never shown again">
            <SecretInput
              label="Broker password"
              isSet={connection.passwordSet}
              value={form.password}
              removed={form.clearPassword}
              onChange={(password) => set({ password, clearPassword: false })}
              onRemove={() => set({ password: '', clearPassword: true })}
              placeholder="Password"
            />
          </FormField>
          <FormField label="Client ID" hint="Empty: centerline-monitor-<computer name>">
            <Input
              value={form.clientId}
              onChange={(e) => set({ clientId: e.target.value })}
              placeholder="centerline-monitor-control-room"
              className="h-8 text-[13px]"
              aria-label="MQTT client ID"
            />
          </FormField>
          <FormField label="Keep-alive (s)" error={err('keepaliveS')} hint="A lost broker is noticed within 1.5 × this">
            <Input
              type="number"
              min={2}
              max={60}
              value={form.keepaliveS}
              onChange={(e) => set({ keepaliveS: Number(e.target.value) })}
              className="h-8 text-[13px]"
              aria-label="Keep-alive seconds"
            />
          </FormField>
        </div>

        <FormField
          label="Topic filters"
          error={err('subscriptions')}
          hint="One per line. The default covers the Volpak filler's areas (SPC, Dosing_Parameters)."
        >
          <Textarea
            rows={2}
            value={form.subscriptions.join('\n')}
            onChange={(e) => set({ subscriptions: e.target.value.split('\n') })}
            className="font-mono text-[12px]"
            aria-label="Topic filters"
          />
        </FormField>

        <FormField
          label="Freshness per machine area"
          error={err('freshnessS')}
          hint="Monitoring pauses when an area is silent longer than this. Measured on 28 days: SPC 30 s, Dosing 90 s (ADR-0006)."
        >
          <div className="flex flex-wrap gap-3">
            {Object.entries(form.freshnessS).map(([area, seconds]) => (
              <label key={area} className="flex items-center gap-2 text-[13px]">
                <span className="text-ink-soft">{area}</span>
                <Input
                  type="number"
                  min={5}
                  max={600}
                  value={seconds}
                  onChange={(e) => set({ freshnessS: { ...form.freshnessS, [area]: Number(e.target.value) } })}
                  className="h-8 w-20 text-[13px]"
                  aria-label={`${area} freshness seconds`}
                />
                <span className="text-ink-muted text-[12px]">s</span>
              </label>
            ))}
          </div>
        </FormField>

        <FormField label="Reason for the change" hint="Optional; kept in the change history">
          <Input
            value={form.reason}
            onChange={(e) => set({ reason: e.target.value })}
            placeholder="e.g. Broker details from the UNS team"
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
          <Button type="button" variant="outline" size="sm" disabled={busy !== null || !form.host} onClick={() => void run('test')}>
            {busy === 'test' ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <PlugZap className="size-4" aria-hidden />}
            {busy === 'test' ? `Listening ${TEST_SECONDS} s…` : 'Test connection'}
          </Button>
          <Button type="submit" size="sm" disabled={busy !== null || !form.host}>
            {busy === 'save' ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Save className="size-4" aria-hidden />}
            Save
          </Button>
        </div>
      </form>

      {check && <MqttCheckResult check={check} />}
    </SectionCard>
  )
}

function MqttCheckResult({ check }: { check: MqttCheck }) {
  if (!check.connected) {
    return (
      <div className="border-critical-border bg-critical-surface mt-4 rounded-md border px-3 py-2.5 text-[13px]" role="status">
        <p className="text-critical flex items-center gap-1.5 font-medium">
          <XCircle className="size-4" aria-hidden /> Not connected
        </p>
        <p className="text-ink mt-1">{check.error}</p>
      </div>
    )
  }
  const mapped = check.mapped ?? []
  const missing = check.missing ?? []
  return (
    <div className="border-line mt-4 flex flex-col gap-3 rounded-md border p-3" role="status">
      <p className="text-normal flex items-center gap-1.5 text-[13px] font-medium">
        <CheckCircle2 className="size-4" aria-hidden />
        Connected · listened {check.listenedS} s · {check.topicCount} topic{check.topicCount === 1 ? '' : 's'} ·{' '}
        {mapped.length} of {mapped.length + missing.length} register tags found
      </p>
      {(check.warnings ?? []).map((w) => (
        <p key={w} className="text-ink flex items-start gap-1.5 text-[12px]">
          <TriangleAlert className="text-warning mt-0.5 size-3.5 shrink-0" aria-hidden /> {w}
        </p>
      ))}
      {(check.topics ?? []).length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-ink-muted border-line border-b text-left text-[11px] uppercase">
                <th className="py-1.5 pr-3 font-semibold">Topic</th>
                <th className="py-1.5 pr-3 text-right font-semibold">Msgs / min</th>
                <th className="py-1.5 pr-3 font-semibold">Format</th>
                <th className="py-1.5 pr-3 text-right font-semibold">Fields</th>
                <th className="py-1.5 font-semibold">Retained</th>
              </tr>
            </thead>
            <tbody>
              {(check.topics ?? []).map((t) => (
                <tr key={t.topic} className="border-line-soft border-b last:border-0">
                  <td className="max-w-[340px] truncate py-1.5 pr-3 font-mono" title={t.topic}>
                    {t.topic}
                  </td>
                  <td className="tnum py-1.5 pr-3 text-right">{t.perMinute}</td>
                  <td className="py-1.5 pr-3">{t.format ?? '—'}</td>
                  <td className="tnum py-1.5 pr-3 text-right">{t.fields}</td>
                  <td className="py-1.5">{t.retained ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {missing.length > 0 && (
        <details className="text-[12px]">
          <summary className="text-ink-soft cursor-pointer">{missing.length} register tags not seen</summary>
          <ul className="mt-1 grid grid-cols-1 gap-x-4 sm:grid-cols-2">
            {missing.map((m) => (
              <li key={m.tag} className="font-mono">
                {m.tag} <span className="text-ink-muted font-sans">({m.label})</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {(check.skuCandidates ?? []).length > 0 && (
        <p className="text-[12px]">
          SKU-like fields:{' '}
          {(check.skuCandidates ?? []).map((s) => (
            <span key={`${s.topic}.${s.field}`} className="font-mono">
              {s.field}={s.value}{' '}
            </span>
          ))}
        </p>
      )}
    </div>
  )
}
