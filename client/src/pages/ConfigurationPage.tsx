import { FileClock, Info, Settings2, Sliders } from 'lucide-react'
import { useMemo, useState } from 'react'

import { ParameterConfigurationModal } from '@/components/centerline/ParameterConfigurationModal'
import { SetpointHistoryTimeline } from '@/components/centerline/SetpointHistoryTimeline'
import { EmptyState } from '@/components/shared/EmptyState'
import { ListSkeleton, TableSkeleton } from '@/components/shared/LoadingSkeleton'
import { PageHeader } from '@/components/shared/PageHeader'
import { SectionCard } from '@/components/shared/SectionCard'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useCenterline } from '@/hooks/useCenterline'
import { CATEGORY_LABELS, type CenterlineRow } from '@/types'
import { formatNumber } from '@/utils/format'

export function ConfigurationPage() {
  const { loading, parameters, centerlineRows, setpointHistory } = useCenterline()

  const [configRow, setConfigRow] = useState<CenterlineRow | null>(null)
  const [configOpen, setConfigOpen] = useState(false)

  /** One editable row per parameter definition, using its first reading as the
   *  concrete machine/SKU context the modal edits against. */
  const editable = useMemo(
    () =>
      parameters.map((parameter) => ({
        parameter,
        row: centerlineRows.find((row) => row.parameter.id === parameter.id) ?? null,
      })),
    [parameters, centerlineRows],
  )

  const recentChanges = useMemo(
    () => [...setpointHistory].sort((a, b) => b.changedAt.localeCompare(a.changedAt)),
    [setpointHistory],
  )

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Configuration"
        description="Parameter definitions, tolerance bands and the full setpoint change audit."
        breadcrumbs={[{ label: 'Setup' }, { label: 'Configuration' }]}
      />

      <p className="text-ink-soft bg-brand-surface border-brand/20 flex items-start gap-2 rounded-lg border px-4 py-3 text-[13px] leading-relaxed">
        <Info className="text-brand mt-0.5 size-4 shrink-0" aria-hidden />
        <span>
          This prototype edits local React state only. Changes are visible across the
          application for the current session and are discarded on reload — nothing is
          written to a machine, historian or server.
        </span>
      </p>

      <SectionCard
        title="Parameter registry"
        description="Every monitored parameter, its unit, allowable range and tolerance bands"
        icon={Sliders}
        bodyClassName="p-0"
        flush
      >
        {loading ? (
          <TableSkeleton rows={8} columns={7} />
        ) : editable.length === 0 ? (
          <EmptyState
            icon={Sliders}
            title="No parameters defined"
            description="No parameter definitions exist in this dataset."
            compact
          />
        ) : (
          <div className="min-w-0 overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Parameter</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Unit</TableHead>
                  <TableHead className="text-right">Min</TableHead>
                  <TableHead className="text-right">Max</TableHead>
                  <TableHead className="text-right">Warning</TableHead>
                  <TableHead className="text-right">Critical</TableHead>
                  <TableHead className="text-right">Machines</TableHead>
                  <TableHead className="w-24 text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {editable.map(({ parameter, row }) => (
                  <TableRow key={parameter.id}>
                    <TableCell className="font-medium">
                      <span className="block">{parameter.name}</span>
                      <span className="text-ink-muted block max-w-md truncate text-[11px] font-normal">
                        {parameter.description}
                      </span>
                    </TableCell>
                    <TableCell className="text-ink-soft">
                      {CATEGORY_LABELS[parameter.category]}
                    </TableCell>
                    <TableCell className="text-ink-soft">{parameter.unit}</TableCell>
                    <TableCell className="tnum text-ink-soft text-right">
                      {formatNumber(parameter.minAllowed, parameter.decimals)}
                    </TableCell>
                    <TableCell className="tnum text-ink-soft text-right">
                      {formatNumber(parameter.maxAllowed, parameter.decimals)}
                    </TableCell>
                    <TableCell className="tnum text-warning text-right font-medium">
                      ±{formatNumber(parameter.warningTolerancePct, 1)}%
                    </TableCell>
                    <TableCell className="tnum text-critical text-right font-medium">
                      ±{formatNumber(parameter.criticalTolerancePct, 1)}%
                    </TableCell>
                    <TableCell className="tnum text-ink-soft text-right">
                      {parameter.machineIds.length}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={row === null}
                        onClick={() => {
                          if (!row) return
                          setConfigRow(row)
                          setConfigOpen(true)
                        }}
                        className="gap-1.5"
                      >
                        <Settings2 className="size-3.5" aria-hidden />
                        Edit
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </SectionCard>

      <SectionCard
        title="Setpoint change audit"
        description="Every recorded configuration change across all parameters and machines"
        icon={FileClock}
      >
        {loading ? (
          <ListSkeleton rows={4} />
        ) : (
          <SetpointHistoryTimeline changes={recentChanges} limit={12} />
        )}
      </SectionCard>

      <ParameterConfigurationModal
        row={configRow}
        open={configOpen}
        onOpenChange={setConfigOpen}
      />
    </div>
  )
}
