import { KeyRound } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { cn } from '@/utils/cn'

export function FormField({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: string
  hint?: ReactNode
  error?: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('min-w-0', className)}>
      <span className="micro-label mb-1.5 block">{label}</span>
      {children}
      {error ? (
        <p className="text-critical mt-1 text-[12px] leading-snug">{error}</p>
      ) : hint ? (
        <p className="text-ink-muted mt-1 text-[11px] leading-snug">{hint}</p>
      ) : null}
    </div>
  )
}

/**
 * A write-only secret. When one is saved, the field shows "Saved" and never the
 * value; typing a new one replaces it on save, leaving it empty keeps it.
 */
export function SecretInput({
  isSet,
  value,
  onChange,
  onRemove,
  removed = false,
  placeholder,
  label,
}: {
  isSet: boolean
  value: string
  onChange: (value: string) => void
  onRemove?: () => void
  removed?: boolean
  placeholder: string
  label: string
}) {
  const [editing, setEditing] = useState(!isSet)
  if (isSet && !editing && !removed) {
    return (
      <div className="border-line bg-surface-muted flex h-8 items-center justify-between gap-2 rounded-md border px-2.5">
        <span className="flex items-center gap-1.5 text-[13px]">
          <KeyRound className="text-ink-muted size-3.5" aria-hidden />
          <Badge variant="normal">Saved</Badge>
          <span className="text-ink-muted text-[12px]">not shown</span>
        </span>
        <span className="flex gap-1">
          <Button type="button" variant="ghost" size="sm" className="h-6 px-2 text-[12px]" onClick={() => setEditing(true)}>
            Change
          </Button>
          {onRemove && (
            <Button type="button" variant="ghost" size="sm" className="text-critical h-6 px-2 text-[12px]" onClick={onRemove}>
              Remove
            </Button>
          )}
        </span>
      </div>
    )
  }
  return (
    <div className="flex gap-1.5">
      <Input
        type="password"
        autoComplete="new-password"
        aria-label={label}
        value={value}
        placeholder={removed ? 'Removed on save' : placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 text-[13px]"
      />
      {isSet && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 shrink-0 px-2 text-[12px]"
          onClick={() => {
            onChange('')
            setEditing(false)
          }}
        >
          Keep saved
        </Button>
      )}
    </div>
  )
}

export function CheckRow({
  checked,
  onChange,
  label,
  description,
  disabled = false,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  description?: string
  disabled?: boolean
}) {
  return (
    <label className={cn('flex items-start gap-2.5 text-[13px]', disabled && 'opacity-50')}>
      <Checkbox
        checked={checked}
        disabled={disabled}
        onCheckedChange={(next) => onChange(next === true)}
        className="mt-0.5"
      />
      <span>
        <span className="text-ink font-medium">{label}</span>
        {description && <span className="text-ink-soft block text-[12px]">{description}</span>}
      </span>
    </label>
  )
}
