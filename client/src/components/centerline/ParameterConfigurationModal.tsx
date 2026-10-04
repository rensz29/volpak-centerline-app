import { zodResolver } from '@hookform/resolvers/zod'
import { Info, Save } from 'lucide-react'
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { ParameterConfigUpdate } from '@/context/CenterlineContext'
import { useCenterline } from '@/hooks/useCenterline'
import type { CenterlineRow } from '@/types'
import { cn } from '@/utils/cn'

/**
 * Validation mirrors the physical constraints of a setpoint: the allowable
 * range must be coherent, both setpoints must sit inside it, and the warning
 * band must be tighter than the critical band or the statuses could never be
 * reached in order.
 */
const configSchema = z
  .object({
    name: z.string().trim().min(2, 'Enter a parameter name.').max(60, 'Keep the name under 60 characters.'),
    unit: z.string().trim().min(1, 'Enter a unit.').max(12, 'Keep the unit short.'),
    minAllowed: z.coerce.number<number>().finite('Enter a number.'),
    maxAllowed: z.coerce.number<number>().finite('Enter a number.'),
    targetSetpoint: z.coerce.number<number>().finite('Enter a number.'),
    hmiSetpoint: z.coerce.number<number>().finite('Enter a number.'),
    warningTolerancePct: z.coerce
      .number<number>()
      .gt(0, 'Must be greater than 0.')
      .max(100, 'Cannot exceed 100%.'),
    criticalTolerancePct: z.coerce
      .number<number>()
      .gt(0, 'Must be greater than 0.')
      .max(100, 'Cannot exceed 100%.'),
    machineId: z.string().min(1, 'Select a machine.'),
    skuId: z.string().min(1, 'Select a SKU.'),
    reason: z
      .string()
      .trim()
      .min(10, 'Give at least 10 characters explaining the change.')
      .max(280, 'Keep the reason under 280 characters.'),
  })
  .refine((data) => data.minAllowed < data.maxAllowed, {
    path: ['maxAllowed'],
    message: 'Maximum must be greater than the minimum.',
  })
  .refine(
    (data) => data.targetSetpoint >= data.minAllowed && data.targetSetpoint <= data.maxAllowed,
    { path: ['targetSetpoint'], message: 'Target must sit inside the allowable range.' },
  )
  .refine(
    (data) => data.hmiSetpoint >= data.minAllowed && data.hmiSetpoint <= data.maxAllowed,
    { path: ['hmiSetpoint'], message: 'HMI value must sit inside the allowable range.' },
  )
  .refine((data) => data.warningTolerancePct < data.criticalTolerancePct, {
    path: ['criticalTolerancePct'],
    message: 'Critical tolerance must be wider than the warning tolerance.',
  })

type ConfigFormValues = z.input<typeof configSchema>

interface ParameterConfigurationModalProps {
  row: CenterlineRow | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ParameterConfigurationModal({
  row,
  open,
  onOpenChange,
}: ParameterConfigurationModalProps) {
  const { machines, skus, updateParameterConfig } = useCenterline()

  const form = useForm<ConfigFormValues>({
    resolver: zodResolver(configSchema),
    mode: 'onBlur',
  })

  const { register, handleSubmit, reset, setValue, watch, formState } = form
  const { errors, isSubmitting } = formState

  // Re-seed the form each time a different parameter is opened.
  useEffect(() => {
    if (!row || !open) return
    reset({
      name: row.parameter.name,
      unit: row.parameter.unit,
      minAllowed: row.parameter.minAllowed,
      maxAllowed: row.parameter.maxAllowed,
      targetSetpoint: row.reading.targetSetpoint,
      hmiSetpoint: row.reading.hmiSetpoint,
      warningTolerancePct: row.parameter.warningTolerancePct,
      criticalTolerancePct: row.parameter.criticalTolerancePct,
      machineId: row.reading.machineId,
      skuId: row.reading.skuId,
      reason: '',
    })
  }, [row, open, reset])

  if (!row) return null

  const onSubmit = (values: ConfigFormValues) => {
    const parsed = configSchema.parse(values)

    const update: ParameterConfigUpdate = {
      readingId: row.id,
      parameterId: row.parameter.id,
      name: parsed.name,
      unit: parsed.unit,
      minAllowed: parsed.minAllowed,
      maxAllowed: parsed.maxAllowed,
      targetSetpoint: parsed.targetSetpoint,
      hmiSetpoint: parsed.hmiSetpoint,
      warningTolerancePct: parsed.warningTolerancePct,
      criticalTolerancePct: parsed.criticalTolerancePct,
      machineId: parsed.machineId,
      skuId: parsed.skuId,
      reason: parsed.reason,
    }

    const changedFields = updateParameterConfig(update)
    onOpenChange(false)

    if (changedFields === 0) {
      toast.success('Configuration saved', {
        description: `${parsed.name} was saved with no numeric changes.`,
      })
    } else {
      toast.success('Configuration updated', {
        description: `${changedFields} ${changedFields === 1 ? 'value' : 'values'} changed on ${parsed.name}. The change was added to the audit history.`,
      })
    }
  }

  const machineId = watch('machineId')
  const skuId = watch('skuId')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit parameter configuration</DialogTitle>
          <DialogDescription>
            {row.parameter.name} on {row.machineName} · {row.skuCode}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="flex min-h-0 flex-1 flex-col">
          <DialogBody className="space-y-5">
            <FieldGroup title="Identity">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field
                  label="Parameter name"
                  error={errors.name?.message}
                  className="sm:col-span-2"
                >
                  <Input {...register('name')} aria-invalid={Boolean(errors.name)} />
                </Field>
                <Field label="Unit" error={errors.unit?.message}>
                  <Input {...register('unit')} aria-invalid={Boolean(errors.unit)} />
                </Field>
              </div>
            </FieldGroup>

            <FieldGroup
              title="Allowable range"
              hint="The physical limits the parameter may be configured within."
            >
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Field label="Minimum allowable value" error={errors.minAllowed?.message}>
                  <NumberInput
                    {...register('minAllowed')}
                    suffix={row.parameter.unit}
                    aria-invalid={Boolean(errors.minAllowed)}
                  />
                </Field>
                <Field label="Maximum allowable value" error={errors.maxAllowed?.message}>
                  <NumberInput
                    {...register('maxAllowed')}
                    suffix={row.parameter.unit}
                    aria-invalid={Boolean(errors.maxAllowed)}
                  />
                </Field>
              </div>
            </FieldGroup>

            <FieldGroup
              title="Setpoints"
              hint="Target is the engineering centerline; HMI is the value on the machine panel."
            >
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Field label="Target setpoint" error={errors.targetSetpoint?.message}>
                  <NumberInput
                    {...register('targetSetpoint')}
                    suffix={row.parameter.unit}
                    aria-invalid={Boolean(errors.targetSetpoint)}
                  />
                </Field>
                <Field label="HMI setpoint" error={errors.hmiSetpoint?.message}>
                  <NumberInput
                    {...register('hmiSetpoint')}
                    suffix={row.parameter.unit}
                    aria-invalid={Boolean(errors.hmiSetpoint)}
                  />
                </Field>
              </div>
            </FieldGroup>

            <FieldGroup
              title="Tolerances"
              hint="Percentage deviation from target at which each status is raised."
            >
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Field
                  label="Warning tolerance"
                  error={errors.warningTolerancePct?.message}
                >
                  <NumberInput
                    {...register('warningTolerancePct')}
                    suffix="%"
                    aria-invalid={Boolean(errors.warningTolerancePct)}
                  />
                </Field>
                <Field
                  label="Critical tolerance"
                  error={errors.criticalTolerancePct?.message}
                >
                  <NumberInput
                    {...register('criticalTolerancePct')}
                    suffix="%"
                    aria-invalid={Boolean(errors.criticalTolerancePct)}
                  />
                </Field>
              </div>
            </FieldGroup>

            <FieldGroup title="Applies to">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Field label="Machine" error={errors.machineId?.message}>
                  <Select
                    value={machineId}
                    onValueChange={(value) =>
                      setValue('machineId', value, { shouldValidate: true })
                    }
                  >
                    <SelectTrigger aria-label="Machine">
                      <SelectValue placeholder="Select a machine" />
                    </SelectTrigger>
                    <SelectContent>
                      {machines.map((machine) => (
                        <SelectItem key={machine.id} value={machine.id}>
                          {machine.name} — {machine.code}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="SKU" error={errors.skuId?.message}>
                  <Select
                    value={skuId}
                    onValueChange={(value) =>
                      setValue('skuId', value, { shouldValidate: true })
                    }
                  >
                    <SelectTrigger aria-label="SKU">
                      <SelectValue placeholder="Select a SKU" />
                    </SelectTrigger>
                    <SelectContent>
                      {skus.map((sku) => (
                        <SelectItem key={sku.id} value={sku.id}>
                          {sku.code} — {sku.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
              </div>
            </FieldGroup>

            <FieldGroup
              title="Audit"
              hint="Every setpoint change is recorded against the parameter."
            >
              <Field label="Reason for change" error={errors.reason?.message}>
                <Textarea
                  {...register('reason')}
                  placeholder="e.g. Seal integrity trial concluded; centerline raised 2 °C per QA report QA-2291."
                  aria-invalid={Boolean(errors.reason)}
                />
              </Field>
            </FieldGroup>

            <p className="text-ink-soft bg-surface-muted border-line flex items-start gap-2 rounded-md border px-3 py-2.5 text-[12px]">
              <Info className="text-brand mt-px size-4 shrink-0" aria-hidden />
              This prototype updates local state only. Nothing is written to a machine,
              a historian or a server.
            </p>
          </DialogBody>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting} className="gap-1.5">
              <Save className="size-4" aria-hidden />
              Save configuration
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function FieldGroup({
  title,
  hint,
  children,
}: {
  title: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <fieldset>
      <legend className="micro-label mb-0.5">{title}</legend>
      {hint && <p className="text-ink-muted mb-2.5 text-[12px]">{hint}</p>}
      <div className={cn(!hint && 'mt-2.5')}>{children}</div>
    </fieldset>
  )
}

function Field({
  label,
  error,
  children,
  className,
}: {
  label: string
  error?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('min-w-0', className)}>
      <Label className="mb-1.5">{label}</Label>
      {children}
      {error && (
        <p role="alert" className="text-critical mt-1.5 text-[12px]">
          {error}
        </p>
      )}
    </div>
  )
}

function NumberInput({
  suffix,
  className,
  ...props
}: React.ComponentProps<'input'> & { suffix?: string }) {
  return (
    <div className="relative">
      <Input
        type="number"
        step="any"
        inputMode="decimal"
        className={cn('tnum pr-12', className)}
        {...props}
      />
      {suffix && (
        <span className="text-ink-muted pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-[12px]">
          {suffix}
        </span>
      )}
    </div>
  )
}
