import type { LucideIcon } from 'lucide-react'

import { cn } from '@/utils/cn'

import { TONE, type Tone } from './liveModel'

/** Never colour alone: a dot, an icon and a written label, as on the rest of the app. */
export function StateBadge({ tone, icon: Icon, label, title, className }: {
  tone: Tone
  icon: LucideIcon
  label: string
  title?: string
  className?: string
}) {
  return (
    <span
      title={title}
      className={cn('inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[12px] font-medium whitespace-nowrap', TONE[tone].badge, className)}
    >
      <span className={cn('size-2 shrink-0 rounded-full', TONE[tone].dot)} aria-hidden />
      <Icon className="size-3.5 shrink-0" aria-hidden />
      {label}
    </span>
  )
}
