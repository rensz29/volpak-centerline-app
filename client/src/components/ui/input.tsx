import type * as React from 'react'

import { cn } from '@/utils/cn'

function Input({ className, type, ...props }: React.ComponentProps<'input'>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        'border-line bg-surface text-ink placeholder:text-ink-muted flex h-9 w-full rounded-md border px-3 py-1 text-sm transition-colors duration-150 outline-none',
        'focus-visible:border-brand-ring focus-visible:ring-brand-ring/40 focus-visible:ring-2',
        'aria-invalid:border-critical aria-invalid:ring-critical/20 aria-invalid:ring-2',
        'disabled:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60',
        'file:text-ink file:inline-flex file:border-0 file:bg-transparent file:text-sm file:font-medium',
        className,
      )}
      {...props}
    />
  )
}

export { Input }
