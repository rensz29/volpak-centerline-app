import { KeyRound, Lock, Pencil, UserPlus, UsersRound } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'

import { AccountDialog, ResetDialog, TemporaryPasswordDialog } from '@/components/accounts/AccountDialogs'
import { EmptyState } from '@/components/shared/EmptyState'
import { TableSkeleton } from '@/components/shared/LoadingSkeleton'
import { PageHeader } from '@/components/shared/PageHeader'
import { SectionCard } from '@/components/shared/SectionCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { accountsApi } from '@/services/authApi'
import { ROLE_LABEL, type Account, type TemporaryPassword } from '@/types/authApi'
import { formatManilaShort } from '@/utils/manilaTime'

const when = (iso: string | null) => (iso ? `${formatManilaShort(Date.parse(iso))}` : '—')

/** `now`: when the list was loaded, so a lock or a temporary password reads as of then. */
function State({ a, now }: { a: Account; now: number }) {
  if (!a.active) return <Badge variant="neutral">Disabled</Badge>
  if (a.lockedUntil && Date.parse(a.lockedUntil) > now)
    return (
      <Badge variant="critical">
        <Lock className="size-3" aria-hidden /> Locked until {when(a.lockedUntil)}
      </Badge>
    )
  if (a.mustChange)
    return a.temporaryExpiresAt && Date.parse(a.temporaryExpiresAt) <= now ? (
      <Badge variant="warning">Temporary password expired</Badge>
    ) : (
      <Badge variant="warning">Temporary password until {when(a.temporaryExpiresAt)}</Badge>
    )
  return <Badge variant="normal">Active</Badge>
}

/** Accounts (ADR-0016), for Administrators: who can sign in, with which roles. */
export function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[] | null>(null)
  const [loadedAt, setLoadedAt] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Account | 'new' | null>(null)
  const [resetting, setResetting] = useState<Account | null>(null)
  const [shown, setShown] = useState<TemporaryPassword | null>(null)

  const load = useCallback(() => {
    accountsApi
      .list()
      .then((r) => {
        setAccounts(r.accounts)
        setLoadedAt(Date.now())
      })
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : String(caught)))
  }, [])
  useEffect(load, [load])

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Accounts"
        description="Who can sign in, with which roles. Accounts are disabled, never deleted: the audit log names them."
        breadcrumbs={[{ label: 'Setup' }, { label: 'Accounts' }]}
        actions={
          <Button type="button" size="sm" onClick={() => setEditing('new')}>
            <UserPlus className="size-4" aria-hidden /> New account
          </Button>
        }
      />

      <SectionCard title="Accounts" description={accounts ? `${accounts.filter((a) => a.active).length} can sign in` : ' '}
                   icon={UsersRound} flush>
        {error ? (
          <EmptyState icon={UsersRound} title="Can't load the accounts" description={error} />
        ) : !accounts ? (
          <TableSkeleton rows={4} />
        ) : (
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-ink-muted border-line border-b text-left text-[11px] uppercase">
                <th className="px-5 py-2 font-semibold">Name</th>
                <th className="px-3 py-2 font-semibold">Also signs in as</th>
                <th className="px-3 py-2 font-semibold">Roles</th>
                <th className="px-3 py-2 font-semibold">State</th>
                <th className="px-3 py-2 font-semibold">Last sign-in</th>
                <th className="px-3 py-2 font-semibold">Sessions</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.id} className="border-line-soft border-b">
                  <td className="px-5 py-2">
                    <span className="text-ink font-medium">{a.displayName}</span>
                    <span className="text-ink-muted ml-2 font-mono text-[12px]">{a.username}</span>
                  </td>
                  <td className="text-ink-soft px-3 py-2 text-[12px]">{[a.email, a.employeeId].filter(Boolean).join(' · ') || '—'}</td>
                  <td className="px-3 py-2">
                    <span className="flex flex-wrap gap-1">
                      {a.roles.map((r) => (
                        <Badge key={r} variant="outline">
                          {ROLE_LABEL[r]}
                        </Badge>
                      ))}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <State a={a} now={loadedAt} />
                  </td>
                  <td className="text-ink-soft px-3 py-2 text-[12px]">{when(a.lastSignInAt)}</td>
                  <td className="text-ink-soft px-3 py-2 tabular-nums">{a.sessions}</td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <Button type="button" variant="ghost" size="sm" onClick={() => setEditing(a)}>
                      <Pencil className="size-3.5" aria-hidden /> Change
                    </Button>
                    <Button type="button" variant="ghost" size="sm" onClick={() => setResetting(a)}>
                      <KeyRound className="size-3.5" aria-hidden /> Temporary password
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>

      {editing && (
        <AccountDialog
          account={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={({ temporary, signedOut, you }) => {
            setEditing(null)
            if (temporary) setShown(temporary)
            else toast.success(signedOut ? `Saved: ${signedOut} session(s) signed out` : 'Saved')
            if (!you || !signedOut) load() // after changing your own roles you're signed out: nothing to reload
          }}
        />
      )}
      {resetting && (
        <ResetDialog
          account={resetting}
          onClose={() => setResetting(null)}
          onDone={(result) => {
            setResetting(null)
            setShown(result)
            load()
          }}
        />
      )}
      {shown && (
        <TemporaryPasswordDialog
          result={shown}
          onClose={() => {
            setShown(null)
            load()
          }}
        />
      )}
    </div>
  )
}
