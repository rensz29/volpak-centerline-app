import { useState } from 'react'

import { Input } from '@/components/ui/input'
import { cn } from '@/utils/cn'

/**
 * A number that may be left blank (null: inherited). Keeps the text as typed, so
 * "0." or "-" can be on the way to a number; only valid numbers reach onChange.
 */
export function NumberField({
  value,
  onChange,
  label,
  placeholder,
  unit,
  integer = false,
  min,
  invalid = false,
  disabled = false,
  className,
}: {
  value: number | null
  onChange: (value: number | null) => void
  label: string
  placeholder?: string
  unit?: string | null
  integer?: boolean
  min?: number
  invalid?: boolean
  disabled?: boolean
  className?: string
}) {
  const [text, setText] = useState(value === null ? '' : String(value))
  const [shown, setShown] = useState(value)
  if (value !== shown) {
    // changed from outside (e.g. "fill from current setpoints"): show the new value
    setShown(value)
    setText(value === null ? '' : String(value))
  }
  const parsed = text.trim() === '' ? null : Number(text)
  const bad =
    parsed !== null && (!Number.isFinite(parsed) || (integer && !Number.isInteger(parsed)) || (min !== undefined && parsed < min))

  return (
    <div className={cn('relative min-w-0', className)}>
      <Input
        type="text"
        inputMode={integer ? 'numeric' : 'decimal'}
        aria-label={label}
        aria-invalid={invalid || bad || undefined}
        value={text}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(event) => {
          const next = event.target.value
          setText(next)
          const n = next.trim() === '' ? null : Number(next)
          if (n === null || (Number.isFinite(n) && (!integer || Number.isInteger(n)) && (min === undefined || n >= min))) {
            setShown(n)
            onChange(n)
          }
        }}
        className={cn(
          'h-8 text-right font-mono text-[12px] tabular-nums placeholder:font-sans placeholder:text-[11px]',
          unit && 'pr-9',
          (invalid || bad) && 'border-critical-border focus-visible:ring-critical',
        )}
      />
      {unit && (
        <span className="text-ink-muted pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 text-[11px]">{unit}</span>
      )}
    </div>
  )
}
