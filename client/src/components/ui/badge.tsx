import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import type * as React from 'react'

import { cn } from '@/utils/cn'

const badgeVariants = cva(
  'inline-flex w-fit shrink-0 items-center justify-center gap-1.5 rounded-md border px-2 py-0.5 text-[12px] font-medium whitespace-nowrap [&_svg]:pointer-events-none [&_svg]:size-3.5',
  {
    variants: {
      variant: {
        default: 'border-brand/20 bg-brand-surface text-brand',
        neutral: 'border-line bg-surface-muted text-ink-soft',
        outline: 'border-line bg-surface text-ink-soft',
        normal: 'border-normal-border bg-normal-surface text-normal',
        warning: 'border-warning-border bg-warning-surface text-warning',
        critical: 'border-critical-border bg-critical-surface text-critical',
        nodata: 'border-nodata-border bg-nodata-surface text-nodata',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

interface BadgeProps
  extends React.ComponentProps<'span'>,
    VariantProps<typeof badgeVariants> {
  asChild?: boolean
}

function Badge({ className, variant, asChild = false, ...props }: BadgeProps) {
  const Comp = asChild ? Slot : 'span'
  return (
    <Comp
      data-slot="badge"
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
