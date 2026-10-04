import { Building2, Cpu, Workflow } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ALL } from '@/context/ScopeContext'
import { useCenterline, useScope } from '@/hooks/useCenterline'
import { cn } from '@/utils/cn'

/**
 * Cascading factory → line → machine selector.
 *
 * The options at each level are narrowed by the level above, so the control can
 * never offer a machine that does not belong to the selected line.
 */
export function ScopeSelectors({ className }: { className?: string }) {
  const { factories, lines, machines } = useCenterline()
  const scope = useScope()

  const availableLines =
    scope.factoryId === ALL
      ? lines
      : lines.filter((line) => line.factoryId === scope.factoryId)

  const availableMachines = machines.filter((machine) => {
    if (scope.lineId !== ALL) return machine.lineId === scope.lineId
    if (scope.factoryId !== ALL) return machine.factoryId === scope.factoryId
    return true
  })

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <ScopeSelect
        icon={Building2}
        label="Factory"
        value={scope.factoryId}
        onChange={scope.setFactory}
        allLabel="All factories"
        options={factories.map((factory) => ({ value: factory.id, label: factory.name }))}
        className="w-[178px]"
      />
      <ScopeSelect
        icon={Workflow}
        label="Production line"
        value={scope.lineId}
        onChange={scope.setLine}
        allLabel="All lines"
        options={availableLines.map((line) => ({ value: line.id, label: line.name }))}
        className="w-[178px]"
      />
      <ScopeSelect
        icon={Cpu}
        label="Machine"
        value={scope.machineId}
        onChange={scope.setMachine}
        allLabel="All machines"
        options={availableMachines.map((machine) => ({
          value: machine.id,
          label: machine.name,
        }))}
        className="w-[160px]"
      />
    </div>
  )
}

interface ScopeSelectProps {
  icon: LucideIcon
  label: string
  value: string
  onChange: (value: string) => void
  allLabel: string
  options: ReadonlyArray<{ value: string; label: string }>
  className?: string
}

function ScopeSelect({
  icon: Icon,
  label,
  value,
  onChange,
  allLabel,
  options,
  className,
}: ScopeSelectProps) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        aria-label={label}
        className={cn(
          'border-nav-border bg-nav-raised text-nav-fg-strong hover:bg-nav-hover data-[placeholder]:text-nav-fg h-9',
          'focus-visible:border-nav-accent focus-visible:ring-nav-accent/40',
          '[&>svg]:text-nav-fg',
          className,
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          <Icon className="text-nav-fg size-4 shrink-0" aria-hidden />
          <SelectValue />
        </span>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{allLabel}</SelectItem>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
