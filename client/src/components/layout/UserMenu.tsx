import { ChevronDown, KeyRound, LogOut } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { PasswordForm } from '@/components/auth/PasswordForm'
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useAuth, useSession } from '@/hooks/useAuth'
import { ROLE_LABEL } from '@/types/authApi'

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join('') || '?'

/** The signed-in account (ADR-0016): who, which roles, and signing out. */
export function UserMenu() {
  const { signOut } = useAuth()
  const { user, session } = useSession()
  const [changing, setChanging] = useState(false)
  const roles = user.roles.map((r) => ROLE_LABEL[r]).join(' · ')

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger className="text-nav-fg hover:bg-nav-hover focus-visible:ring-nav-accent flex h-9 items-center gap-2 rounded-md pr-2 pl-1 transition-colors hover:text-white focus-visible:ring-2 focus-visible:outline-none">
          <span className="bg-nav-accent grid size-7 shrink-0 place-items-center rounded-md text-[11px] font-semibold text-white">
            {initials(user.displayName)}
          </span>
          <span className="hidden text-left lg:block">
            <span className="block text-[12px] leading-tight font-medium text-white">{user.displayName}</span>
            <span className="block text-[11px] leading-tight">{roles}</span>
          </span>
          <ChevronDown className="size-3.5 shrink-0" aria-hidden />
        </DropdownMenuTrigger>

        <DropdownMenuContent align="end" className="w-64">
          <div className="px-2.5 py-2">
            <p className="text-ink text-[13px] font-semibold">{user.displayName}</p>
            <p className="text-ink-soft text-[12px]">{user.username}</p>
            <p className="text-ink-muted mt-1 text-[11px]">
              {roles}
              {session.workstation ? ` · at ${session.workstation}` : ''}
            </p>
          </div>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => setChanging(true)}>
            <KeyRound aria-hidden />
            Change password
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onSelect={() => void signOut()}>
            <LogOut aria-hidden />
            Sign out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={changing} onOpenChange={setChanging}>
        <DialogContent className="sm:max-w-[440px]">
          <DialogHeader>
            <DialogTitle>Change your password</DialogTitle>
            <DialogDescription>Your other sessions are signed out; this one stays.</DialogDescription>
          </DialogHeader>
          <DialogBody>
            <PasswordForm
              onCancel={() => setChanging(false)}
              onDone={() => {
                setChanging(false)
                toast.success('Password changed')
              }}
            />
          </DialogBody>
        </DialogContent>
      </Dialog>
    </>
  )
}
