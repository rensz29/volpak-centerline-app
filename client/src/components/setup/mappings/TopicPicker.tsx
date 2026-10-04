import { ChevronsUpDown, Plus, Search, X } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/utils/cn'

import { topicTail } from './mappingModel'
import { TopicText } from './TopicText'

export interface TopicOption {
  topic: string
  /** Heard on the broker in the last listen. */
  heard: boolean
  /** Implied by the connection's topic filters and the register's machine areas. */
  suggested: boolean
  /** Tags in this draft already on it. */
  used: number
}

/**
 * Choose the topic a tag arrives on, from the topics heard on the broker, implied by the
 * subscription or already in use; a topic not in the list can be typed in the search box.
 */
export function TopicPicker({
  value,
  onChange,
  options,
  label,
  invalid = false,
}: {
  value: string
  onChange: (topic: string) => void
  options: TopicOption[]
  label: string
  invalid?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const typed = query.trim()
  const shown = useMemo(() => {
    const q = typed.toLowerCase()
    return q ? options.filter((o) => o.topic.toLowerCase().includes(q)) : options
  }, [options, typed])
  const exact = options.some((o) => o.topic === typed)

  const pick = (topic: string) => {
    onChange(topic)
    setOpen(false)
    setQuery('')
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={label}
          title={value || undefined}
          className={cn(
            'border-line bg-surface hover:bg-surface-muted focus-visible:ring-brand-ring flex h-8 w-full min-w-0 items-center justify-between gap-2 rounded-md border px-2.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none',
            invalid && 'border-critical-border',
          )}
        >
          <span className={cn('truncate font-mono text-[12px]', !value && 'text-ink-muted font-sans')}>
            {value ? topicTail(value) : 'Choose a topic…'}
          </span>
          <ChevronsUpDown className="text-ink-muted size-3.5 shrink-0" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[620px] p-0">
        <div className="border-line flex items-center gap-2 border-b px-2.5 py-2">
          <Search className="text-ink-muted size-3.5" aria-hidden />
          <Input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && typed) {
                e.preventDefault()
                pick(shown.length === 1 && !exact ? shown[0]!.topic : typed)
              }
            }}
            placeholder="Search, or type a topic that isn't listed"
            className="h-7 border-0 px-0 text-[13px] shadow-none focus-visible:ring-0"
            aria-label="Search or type a topic"
          />
        </div>
        <ul className="max-h-[320px] overflow-y-auto py-1" role="listbox" aria-label="Topics">
          {typed && !exact && (
            <li>
              <button
                type="button"
                className="hover:bg-surface-muted flex w-full flex-col items-start px-3 py-1.5 text-left"
                onClick={() => pick(typed)}
              >
                <span className="flex items-center gap-1.5 text-[12px]">
                  <Plus className="size-3.5" aria-hidden /> Use <span className="font-mono">{typed}</span>
                </span>
                {/[+#]/.test(typed) && (
                  <span className="text-critical text-[11px]">+ and # are for subscriptions; a mapping needs one topic</span>
                )}
              </button>
            </li>
          )}
          {value && (
            <li>
              <button
                type="button"
                className="text-ink-soft hover:bg-surface-muted flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-[12px]"
                onClick={() => pick('')}
              >
                <X className="size-3.5" aria-hidden /> No topic
              </button>
            </li>
          )}
          {shown.map((o) => (
            <li key={o.topic}>
              <button
                type="button"
                role="option"
                aria-selected={o.topic === value}
                className={cn(
                  'hover:bg-surface-muted flex w-full flex-col items-start px-3 py-1.5 text-left',
                  o.topic === value && 'bg-surface-selected',
                )}
                onClick={() => pick(o.topic)}
              >
                <span className="font-mono text-[12px]">
                  <TopicText topic={o.topic} />
                </span>
                <span className="text-ink-muted text-[11px]">
                  {[
                    o.heard
                      ? 'heard on the broker'
                      : o.suggested
                        ? 'from the subscription, not heard yet'
                        : o.used
                          ? 'in this mapping'
                          : 'typed in',
                    o.used ? `${o.used} tag${o.used === 1 ? '' : 's'} on it` : null,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
              </button>
            </li>
          ))}
          {shown.length === 0 && !typed && (
            <li className="text-ink-muted px-3 py-3 text-[12px]">No topics yet. Use Fill from the broker, or type one above.</li>
          )}
        </ul>
      </PopoverContent>
    </Popover>
  )
}
