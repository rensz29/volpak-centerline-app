import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { WARN_AT_MIN, minutesLeft, windowScope } from '@/components/live/controlModel'
import { ROUTES } from '@/routes/navigation'
import { monitoringApi } from '@/services/monitoringApi'

const EVERY_MS = 20_000

/**
 * For Administrators on any page (MNT-01): a warning 30 and 5 minutes before a window's planned
 * end, and once when it's overdue, so it's ended or extended rather than forgotten.
 */
export function MaintenanceWatch() {
  const navigate = useNavigate()
  const told = useRef(new Map<string, Set<string>>()) // window → the warnings already shown

  useEffect(() => {
    let timer: number | undefined
    const check = () => {
      monitoringApi
        .control()
        .then((view) => {
          const now = Date.parse(view.serverTime)
          for (const w of view.maintenance) {
            if (w.status !== 'active' && w.status !== 'overdue') continue
            const seen = told.current.get(w.id) ?? new Set<string>()
            told.current.set(w.id, seen)
            const left = minutesLeft(w, now)
            const open = { label: 'Maintenance', onClick: () => navigate(ROUTES.maintenance) }
            if (left < 0) {
              if (!seen.has('overdue')) {
                seen.add('overdue')
                toast.error(`Maintenance overdue on ${windowScope(w)}`, {
                  description: `“${w.reason}” was planned to end ${Math.round(-left)} min ago. It stays in force until you end it.`,
                  duration: Infinity, action: open,
                })
              }
              continue
            }
            const due = WARN_AT_MIN.filter((m) => left <= m && !seen.has(String(m)))
            if (due.length > 0) {
              due.forEach((m) => seen.add(String(m)))
              toast.warning(`Maintenance on ${windowScope(w)} ends in ${Math.max(1, Math.round(left))} min`, {
                description: `“${w.reason}”: end it when the work is done, or move the planned end.`, duration: 30_000, action: open,
              })
            }
          }
        })
        .catch(() => undefined)
        .finally(() => {
          timer = window.setTimeout(check, EVERY_MS)
        })
    }
    check()
    return () => window.clearTimeout(timer)
  }, [navigate])

  return null
}
