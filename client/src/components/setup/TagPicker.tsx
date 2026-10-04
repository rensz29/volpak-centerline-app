import { ChevronsUpDown, Search, X } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { HistorianTag } from '@/types/configApi'
import { cn } from '@/utils/cn'

/**
 * Pick a Timebase tag under this machine. Tags another parameter already uses
 * can't be picked (the api would refuse them too); this parameter's own tags can.
 */
export function TagPicker({
  value,
  onChange,
  tags,
  parameterId,
  label,
  invalid = false,
}: {
  value: string | null
  onChange: (tag: string | null) => void
  tags: HistorianTag[]
  parameterId: string
  label: string
  invalid?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (q ? tags.filter((t) => t.tag.toLowerCase().includes(q)) : tags).slice(0, 200)
  }, [tags, query])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className={cn(
            'border-line bg-surface hover:bg-surface-muted focus-visible:ring-brand-ring flex h-8 w-full min-w-0 items-center justify-between gap-2 rounded-md border px-2.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none',
            invalid && 'border-critical-border',
          )}
        >
          <span className={cn('truncate font-mono text-[12px]', !value && 'text-ink-muted font-sans')}>
            {value ?? 'Choose a tag…'}
          </span>
          <ChevronsUpDown className="text-ink-muted size-3.5 shrink-0" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[440px] p-0">
        <div className="border-line flex items-center gap-2 border-b px-2.5 py-2">
          <Search className="text-ink-muted size-3.5" aria-hidden />
          <Input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search tags, e.g. Vertical or Nozzle"
            className="h-7 border-0 px-0 text-[13px] shadow-none focus-visible:ring-0"
            aria-label="Search Timebase tags"
          />
        </div>
        <ul className="max-h-[300px] overflow-y-auto py-1" role="listbox" aria-label="Timebase tags">
          {value && (
            <li>
              <button
                type="button"
                className="text-ink-soft hover:bg-surface-muted flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-[12px]"
                onClick={() => {
                  onChange(null)
                  setOpen(false)
                }}
              >
                <X className="size-3.5" aria-hidden /> No tag
              </button>
            </li>
          )}
          {shown.map((t) => {
            const takenElsewhere = Boolean(t.usedBy) && !t.usedBy?.startsWith(`${parameterId} `) && !t.usedBy?.startsWith('context')
            return (
              <li key={t.tag}>
                <button
                  type="button"
                  role="option"
                  aria-selected={t.tag === value}
                  disabled={takenElsewhere}
                  className={cn(
                    'hover:bg-surface-muted flex w-full flex-col items-start px-3 py-1.5 text-left disabled:cursor-not-allowed disabled:opacity-50',
                    t.tag === value && 'bg-surface-selected',
                  )}
                  onClick={() => {
                    onChange(t.tag)
                    setOpen(false)
                    setQuery('')
                  }}
                >
                  <span className="font-mono text-[12px]">{t.tag}</span>
                  <span className="text-ink-muted text-[11px]">
                    {t.type || 'value'}
                    {t.usedBy ? ` · used by ${t.usedBy}` : ''}
                  </span>
                </button>
              </li>
            )
          })}
          {shown.length === 0 && <li className="text-ink-muted px-3 py-3 text-[12px]">No tag matches “{query}”.</li>}
        </ul>
      </PopoverContent>
    </Popover>
  )
}
