import { Check, Copy, KeyRound, Loader2 } from 'lucide-react'
import { useState } from 'react'

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
import { accountsApi } from '@/services/authApi'
import type { ApiProblem } from '@/services/http'
import { ROLE_LABEL, type Account, type Role, type TemporaryPassword } from '@/types/authApi'
import { formatManilaFull } from '@/utils/manilaTime'

const ROLE_HELP: Record<Role, string> = {
  OPERATOR: 'Works the line from the operator workstation. An Operator account has no other role.',
  MANAGER: 'Acknowledges Criticals, changes the monitoring rules, uses Analytics.',
  ADMINISTRATOR: 'Manages accounts, connections, tags and mappings; uses Analytics.',
}

/** Create an account, or change one. Its username never changes: the audit log refers to it. */
export function AccountDialog({ account, onSaved, onClose }: {
  account: Account | null
  onSaved: (result: { account: Account; temporary?: TemporaryPassword; signedOut?: number; you?: boolean }) => void
  onClose: () => void
}) {
  const [username, setUsername] = useState(account?.username ?? '')
  const [displayName, setDisplayName] = useState(account?.displayName ?? '')
  const [email, setEmail] = useState(account?.email ?? '')
  const [employeeId, setEmployeeId] = useState(account?.employeeId ?? '')
  const [roles, setRoles] = useState<Role[]>(account?.roles ?? ['MANAGER'])
  const [active, setActive] = useState(account?.active ?? true)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<ApiProblem | null>(null)

  const toggle = (role: Role, on: boolean) => {
    if (role === 'OPERATOR') setRoles(on ? ['OPERATOR'] : [])
    else setRoles((r) => (on ? [...r.filter((x) => x !== 'OPERATOR' && x !== role), role] : r.filter((x) => x !== role)))
  }

  const submit = async () => {
    setBusy(true)
    setProblem(null)
    const fields = { displayName, email: email.trim() || null, employeeId: employeeId.trim() || null, roles, reason }
    try {
      if (account) {
        onSaved(await accountsApi.update(account.id, { ...fields, active }))
      } else {
        const made = await accountsApi.create({ ...fields, username })
        onSaved({ account: made.account, temporary: made })
      }
    } catch (caught) {
      setProblem(asProblem(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>{account ? `Change ${account.username}` : 'New account'}</DialogTitle>
          <DialogDescription>
            {account
              ? 'New roles or disabling sign the account out everywhere at once.'
              : 'The account gets a temporary password that works for 24 h and must be changed at the first sign-in.'}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField label="Username" error={problem?.forField('username')}
                       hint={account ? "Doesn't change: the audit log refers to it" : 'Letters, digits, dots, dashes'}>
              <Input value={username} disabled={Boolean(account)} autoComplete="off" onChange={(e) => setUsername(e.target.value)} />
            </FormField>
            <FormField label="Name" error={problem?.forField('displayName')}>
              <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            </FormField>
            <FormField label="Email (optional)" error={problem?.forField('email')}>
              <Input type="email" value={email} autoComplete="off" onChange={(e) => setEmail(e.target.value)} />
            </FormField>
            <FormField label="Employee ID (optional)" error={problem?.forField('employeeId')}>
              <Input value={employeeId} autoComplete="off" onChange={(e) => setEmployeeId(e.target.value)} />
            </FormField>
          </div>
          <p className="text-ink-muted -mt-2 text-[12px]">The username, email and Employee ID each sign in, in any case.</p>
          <FormField label="Roles" error={problem?.forField('roles')}>
            <div className="flex flex-col gap-2.5">
              {(['OPERATOR', 'MANAGER', 'ADMINISTRATOR'] as Role[]).map((role) => (
                <CheckRow key={role} checked={roles.includes(role)} onChange={(on) => toggle(role, on)} label={ROLE_LABEL[role]}
                          description={ROLE_HELP[role]} />
              ))}
            </div>
          </FormField>
          {account && (
            <CheckRow checked={active} onChange={setActive} label="Can sign in"
                      description="A disabled account stays, with its history; it just can't sign in." />
          )}
          <FormField label="Reason (optional)">
            <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Kept in the change history" />
          </FormField>
          <ProblemLine problem={problem} />
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" size="sm" disabled={busy || !displayName.trim() || roles.length === 0 || (!account && !username.trim())}
                  onClick={() => void submit()}>
            {busy && <Loader2 className="size-4 animate-spin" aria-hidden />} {account ? 'Save' : 'Create account'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Reset to a temporary password: unlocks the account and signs it out everywhere. */
export function ResetDialog({ account, onDone, onClose }: {
  account: Account
  onDone: (result: TemporaryPassword) => void
  onClose: () => void
}) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<ApiProblem | null>(null)
  const submit = async () => {
    setBusy(true)
    try {
      onDone(await accountsApi.temporaryPassword(account.id, reason))
    } catch (caught) {
      setProblem(asProblem(caught))
      setBusy(false)
    }
  }
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle>Temporary password for {account.displayName}</DialogTitle>
          <DialogDescription>
            Their current password stops working, a lock ends, and every session of theirs is signed out.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-3">
          <FormField label="Reason (optional)">
            <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Forgot the password" />
          </FormField>
          <ProblemLine problem={problem} />
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" size="sm" disabled={busy} onClick={() => void submit()}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <KeyRound className="size-4" aria-hidden />} Issue
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** The temporary password, shown this once: it isn't stored anywhere the api can show it again. */
export function TemporaryPasswordDialog({ result, onClose }: { result: TemporaryPassword; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  const copy = () =>
    void navigator.clipboard
      .writeText(result.temporaryPassword)
      .then(() => setCopied(true))
      .catch(() => undefined)
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle>Temporary password for {result.account.displayName}</DialogTitle>
          <DialogDescription>Give it to them in person. It's shown only now.</DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-3">
          <div className="border-line bg-surface-muted flex items-center justify-between gap-3 rounded-lg border px-4 py-3">
            <code className="text-ink font-mono text-[18px] tracking-wide">{result.temporaryPassword}</code>
            <Button type="button" variant="outline" size="sm" onClick={copy}>
              {copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />} {copied ? 'Copied' : 'Copy'}
            </Button>
          </div>
          <p className="text-ink-soft text-[13px]">
            {result.account.username} signs in with it until {formatManilaFull(Date.parse(result.temporaryExpiresAt))} Manila,
            then must choose their own password.
          </p>
        </DialogBody>
        <DialogFooter>
          <Button type="button" size="sm" onClick={onClose}>
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
