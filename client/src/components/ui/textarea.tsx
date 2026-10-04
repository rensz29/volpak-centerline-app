import type * as React from 'react'

import { cn } from '@/utils/cn'

function Textarea({ className, ...props }: React.ComponentProps<'textarea'>) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        'border-line bg-surface text-ink placeholder:text-ink-muted flex min-h-[76px] w-full rounded-md border px-3 py-2 text-sm transition-colors duration-150 outline-none',
        'focus-visible:border-brand-ring focus-visible:ring-brand-ring/40 focus-visible:ring-2',
        'aria-invalid:border-critical aria-invalid:ring-critical/20 aria-invalid:ring-2',
        'disabled:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60',
        className,
      )}
      {...props}
    />
  )
}

export { Textarea }
