import { TriangleAlert } from 'lucide-react'
import { Fragment } from 'react'

import type { MappingRow, RequiredTag, SkuPlace } from '@/types/configApi'

import { groupTags } from './mappingModel'
import { TopicText } from './TopicText'

/** A mapping version, read-only: each tag's topic and field, grouped by parameter. */
export function MappingRowsTable({
  required,
  rows,
  sku,
  skuPlaceholder = null,
}: {
  required: RequiredTag[]
  rows: MappingRow[]
  sku: SkuPlace | null
  skuPlaceholder?: string | null
}) {
  const byTag = new Map(rows.map((r) => [r.tag, r]))
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="text-ink-muted border-line border-b text-left text-[11px] uppercase">
          <th className="py-2 pr-3 font-semibold">Tag</th>
          <th className="px-2 py-2 font-semibold">Topic</th>
          <th className="px-2 py-2 font-semibold">Field</th>
        </tr>
      </thead>
      <tbody>
        {groupTags(required).map((g) => (
          <Fragment key={g.key}>
            <tr className="bg-surface-muted/50 border-line-soft border-b">
              <td colSpan={3} className="py-1.5 pr-3 font-medium">
                {g.title}
              </td>
            </tr>
            {g.tags.map((t) => {
              const row = byTag.get(t.tag)
              return (
                <tr key={t.tag} className="border-line-soft border-b">
                  <td className="py-1.5 pr-3 pl-3">
                    {t.label} <span className="text-ink-muted font-mono text-[11px]">{t.tag}</span>
                  </td>
                  {row ? (
                    <>
                      <td className="px-2 py-1.5 font-mono text-[12px]">
                        <TopicText topic={row.topic} />
                      </td>
                      <td className="px-2 py-1.5 font-mono text-[12px]">{row.field ?? '(whole payload)'}</td>
                    </>
                  ) : (
                    <td colSpan={2} className="text-critical px-2 py-1.5 text-[12px]">
                      <span className="inline-flex items-center gap-1">
                        <TriangleAlert className="size-3" aria-hidden /> no place: the zone can't be monitored
                      </span>
                    </td>
                  )}
                </tr>
              )
            })}
          </Fragment>
        ))}
        <tr className="bg-surface-muted/50 border-line-soft border-b">
          <td colSpan={3} className="py-1.5 pr-3 font-medium">
            SKU
          </td>
        </tr>
        <tr>
          <td className="py-1.5 pr-3 pl-3">Running SKU</td>
          {sku ? (
            <>
              <td className="px-2 py-1.5 font-mono text-[12px]">
                <TopicText topic={sku.topic} />
              </td>
              <td className="px-2 py-1.5 font-mono text-[12px]">{sku.field}</td>
            </>
          ) : (
            <td colSpan={2} className="text-warning px-2 py-1.5 text-[12px]">
              {skuPlaceholder
                ? `placeholder ${skuPlaceholder}: actual values only, until the edge team adds the field (O-15)`
                : 'none yet: the edge team still has to add it (O-15)'}
            </td>
          )}
        </tr>
      </tbody>
    </table>
  )
}
