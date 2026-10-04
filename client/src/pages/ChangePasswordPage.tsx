import { AuthFrame } from '@/components/auth/AuthFrame'
import { PasswordForm } from '@/components/auth/PasswordForm'
import { Button } from '@/components/ui/button'
import { useAuth, useSession } from '@/hooks/useAuth'

/** After signing in with a temporary password, choosing your own comes first (IAM-03). */
export function ChangePasswordPage() {
  const { signOut } = useAuth()
  const { user } = useSession()
  return (
    <AuthFrame
      title="Choose your password"
      description={
        <>
          Welcome, {user.displayName}. You signed in with a temporary password: choose your own to continue.
        </>
      }
    >
      <PasswordForm currentLabel="Temporary password" onDone={() => undefined} />
      <Button type="button" variant="ghost" size="sm" className="mt-3" onClick={() => void signOut()}>
        Sign out instead
      </Button>
    </AuthFrame>
  )
}
