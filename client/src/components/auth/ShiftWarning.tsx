import { Clock } from 'lucide-react'
import { useEffect, useState } from 'react'

import { useAuth } from '@/hooks/useAuth'
import { formatManilaTime } from '@/utils/manilaTime'

/**
 * An operator's session ends with its shift (SES-03, ADR-0025). From 5 min before, a bar says so;
 * at the end the session closes, what wasn't sent is cleared, and the next shift's operator signs in.
 * Managers and Administrators: nothing. It sits under the header, so the header stays usable.
 */
export function ShiftWarning() {
  const { state, signOut } = useAuth()
  const [now, setNow] = useState(() => Date.now())
  const signed = state.status === 'signed-in' && state.info.session.endsWithShift ? state : null

  useEffect(() => {
    if (!signed) return
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [signed])

  // The shift's end on this browser's clock: the server's, less the skew
  const end = signed ? Date.parse(signed.info.shift.endsAt) - signed.skewMs : null
  const left = end === null ? null : Math.ceil((end - now) / 1000)
  const over = left !== null && left <= 0

  useEffect(() => {
    if (over && signed) void signOut(`Your shift ended at ${formatManilaTime(Date.parse(signed.info.shift.endsAt)).slice(0, 5)}. The next shift's operator signs in now.`)
  }, [over, signed, signOut])

  if (!signed || left === null || left <= 0 || left > signed.info.session.shiftWarningS) return null
  const minutes = Math.floor(left / 60)
  return (
    <div role="status" className="bg-warning sticky top-14 z-20 flex items-center justify-center gap-2 px-4 py-2 text-[13px] font-medium text-white">
      <Clock className="size-4 shrink-0" aria-hidden />
      Your shift ends at {formatManilaTime(Date.parse(signed.info.shift.endsAt)).slice(0, 5)} Manila, in{' '}
      <span className="tabular-nums">
        {minutes}:{String(left % 60).padStart(2, '0')}
      </span>
      . Send your reasons now: what isn't sent is cleared when the shift ends.
    </div>
  )
}
