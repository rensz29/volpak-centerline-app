import { Clock } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

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
import { useAuth } from '@/hooks/useAuth'

const REPORT_EVERY_MS = 60_000

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

/**
 * Manager and Administrator sessions end after 15 min without the person's own activity
 * (SES-02). Clicks and keys count, reported at most once a minute; the pages refreshing
 * themselves don't. From 13 min this asks whether they're still there. Operators: nothing.
 */
export function IdleWarning() {
  const { state, stillHere, signOut } = useAuth()
  const [now, setNow] = useState(() => Date.now())
  const lastReport = useRef(0)
  const signed = state.status === 'signed-in' ? state : null
  const limit = signed?.info.session.idleLimitS ?? null

  useEffect(() => {
    if (limit === null) return
    const tick = window.setInterval(() => setNow(Date.now()), 1000)
    const onUse = () => {
      if (Date.now() - lastReport.current < REPORT_EVERY_MS) return
      lastReport.current = Date.now()
      void stillHere().catch(() => undefined)
    }
    window.addEventListener('pointerdown', onUse)
    window.addEventListener('keydown', onUse)
    return () => {
      window.clearInterval(tick)
      window.removeEventListener('pointerdown', onUse)
      window.removeEventListener('keydown', onUse)
    }
  }, [limit, stillHere])

  // The deadline on this browser's clock: the server's last activity plus the limit, less the skew
  const deadline = signed && limit !== null ? Date.parse(signed.info.session.lastActiveAt) + limit * 1000 - signed.skewMs : null
  const left = deadline === null ? null : Math.max(0, Math.ceil((deadline - now) / 1000))
  const expired = left === 0

  useEffect(() => {
    if (expired && limit !== null) void signOut(`Signed out after ${Math.round(limit / 60)} min without activity.`)
  }, [expired, limit, signOut])

  if (!signed || limit === null || left === null) return null
  const warnFor = limit - (signed.info.session.idleWarningS ?? limit)
  return (
    <Dialog open={left > 0 && left <= warnFor}>
      <DialogContent showCloseButton={false} className="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Clock className="text-warning size-5" aria-hidden /> Still there?
          </DialogTitle>
          <DialogDescription>
            Manager and Administrator sessions end after {Math.round(limit / 60)} min without activity.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <p className="text-ink text-[13px]">
            You'll be signed out in <b className="tabular-nums">{clock(left)}</b>.
          </p>
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" size="sm" onClick={() => void signOut()}>
            Sign out now
          </Button>
          <Button type="button" size="sm" onClick={() => void stillHere().catch(() => undefined)}>
            Stay signed in
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
