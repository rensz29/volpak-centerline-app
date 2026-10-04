import { Loader2 } from 'lucide-react'
import { useState } from 'react'

import { FormField } from '@/components/setup/FormParts'
import { ProblemLine } from '@/components/setup/VersionDialogs'
import { asProblem } from '@/components/setup/versionUtils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/hooks/useAuth'
import type { ApiProblem } from '@/services/http'

/** The rules the api checks (IAM-03); shown so nobody has to guess. */
const PASSWORD_RULES =
  'At least 12 characters, not on the list of passwords known from breaches, and not one of your last five. A passphrase of a few words works well.'

/** Change your own password. After a temporary one, it's the only thing you can do (IAM-03). */
export function PasswordForm({ currentLabel = 'Current password', onDone, onCancel }: {
  currentLabel?: string
  onDone: () => void
  onCancel?: () => void
}) {
  const { changePassword } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<ApiProblem | null>(null)
  const mismatch = again.length > 0 && again !== next

  const submit = async () => {
    setBusy(true)
    setProblem(null)
    try {
      await changePassword(current, next)
      onDone()
    } catch (caught) {
      setProblem(asProblem(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
    >
      <FormField label={currentLabel} error={problem?.forField('current')}>
        <Input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} autoFocus />
      </FormField>
      <FormField label="New password" hint={PASSWORD_RULES} error={problem?.forField('new')}>
        <Input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
      </FormField>
      <FormField label="New password again" error={mismatch ? "The two new passwords aren't the same" : undefined}>
        <Input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} />
      </FormField>
      <ProblemLine problem={problem} />
      <div className="flex justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="outline" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" size="sm" disabled={busy || !current || !next || next !== again}>
          {busy && <Loader2 className="size-4 animate-spin" aria-hidden />} Change password
        </Button>
      </div>
    </form>
  )
}
