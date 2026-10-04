import { Info, Loader2, MonitorSmartphone, XCircle } from 'lucide-react'
import { useState } from 'react'

import { AuthFrame } from '@/components/auth/AuthFrame'
import { FormField } from '@/components/setup/FormParts'
import { asProblem } from '@/components/setup/versionUtils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/hooks/useAuth'
import type { ApiProblem } from '@/services/http'

/**
 * Signing in (ADR-0016, IAM-02): a username, email or Employee ID, in any case. At an
 * operator workstation a session with no heartbeat for 5 min can be taken over (SES-04).
 */
export function SignInPage({ reason }: { reason: string | null }) {
  const { signIn } = useAuth()
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<ApiProblem | null>(null)
  const takeover = problem?.body?.takeoverAvailable === true

  const submit = async (take = false) => {
    setBusy(true)
    setProblem(null)
    try {
      await signIn(name, password, take)
    } catch (caught) {
      setProblem(asProblem(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthFrame title="Sign in" description="Use your username, email or Employee ID.">
      {reason && (
        <p className="border-line bg-surface-muted text-ink mb-4 flex items-start gap-2 rounded-lg border px-3 py-2 text-[13px]">
          <Info className="text-ink-muted mt-0.5 size-4 shrink-0" aria-hidden /> {reason}
        </p>
      )}
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <FormField label="Username, email or Employee ID">
          <Input autoComplete="username" autoFocus value={name} onChange={(e) => setName(e.target.value)} />
        </FormField>
        <FormField label="Password">
          <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </FormField>
        {problem && (
          <div role="alert" className="border-critical-border bg-critical-surface rounded-lg border px-3 py-2 text-[13px]">
            <p className="text-critical flex items-center gap-1.5 font-semibold">
              <XCircle className="size-4 shrink-0" aria-hidden /> {problem.title}
            </p>
            <p className="text-ink mt-0.5">{problem.message}</p>
          </div>
        )}
        {takeover && (
          <Button type="button" variant="outline" disabled={busy} onClick={() => void submit(true)}>
            <MonitorSmartphone className="size-4" aria-hidden /> Take over the operator session here
          </Button>
        )}
        <Button type="submit" disabled={busy || !name.trim() || !password}>
          {busy && <Loader2 className="size-4 animate-spin" aria-hidden />} Sign in
        </Button>
      </form>
      <p className="text-ink-muted mt-4 text-[12px]">
        Forgotten your password, or locked out? An Administrator can give you a temporary one.
      </p>
    </AuthFrame>
  )
}
