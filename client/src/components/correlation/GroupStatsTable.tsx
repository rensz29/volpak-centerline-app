import { Layers } from 'lucide-react'

import { SectionCard } from '@/components/shared/SectionCard'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { AnalyticsResult } from '@/types/analyticsApi'

import { formatValue, sentenceCase } from './chartOptions'

const WARNINGS = { INSUFFICIENT_DATA: 'Insufficient data', LOW_SAMPLE_SIZE: 'Low sample size' } as const

/** Statistics by shift or production date (ANA-16, ANA-17: < 3 pairs insufficient, 3–29 low sample size). */
export function GroupStatsTable({ result }: { result: AnalyticsResult }) {
  const groups = result.groups
  if (!groups) return null
  return (
    <SectionCard
      title="Statistics by group"
      description={
        groups.hidden > 0
          ? `${groups.items.length} most recent groups shown; ${groups.hidden} older ones hidden`
          : `${groups.items.length} groups`
      }
      icon={Layers}
      flush
    >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Group</TableHead>
            <TableHead className="text-right">Paired buckets</TableHead>
            <TableHead className="text-right">r</TableHead>
            <TableHead>Strength</TableHead>
            <TableHead className="text-right">Slope</TableHead>
            <TableHead className="text-right">Intercept</TableHead>
            <TableHead className="text-right">R²</TableHead>
            <TableHead>Note</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {groups.items.map((g) => {
            const c = g.correlation
            return (
              <TableRow key={g.key}>
                <TableCell className="font-medium">{g.label}</TableCell>
                <TableCell className="tnum text-right">{g.n.toLocaleString('en-US')}</TableCell>
                <TableCell className="tnum text-right">{c?.r?.toFixed(3) ?? '—'}</TableCell>
                <TableCell>{sentenceCase(c?.strength)}</TableCell>
                <TableCell className="tnum text-right">{formatValue(c?.slope)}</TableCell>
                <TableCell className="tnum text-right">{formatValue(c?.intercept)}</TableCell>
                <TableCell className="tnum text-right">{c?.rSquared?.toFixed(3) ?? '—'}</TableCell>
                <TableCell>
                  {g.warning ? (
                    <Badge variant={g.warning === 'INSUFFICIENT_DATA' ? 'critical' : 'warning'}>
                      {WARNINGS[g.warning]}
                    </Badge>
                  ) : c && !c.computable ? (
                    <span className="text-ink-soft text-[12px]">{c.reason}</span>
                  ) : null}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </SectionCard>
  )
}
