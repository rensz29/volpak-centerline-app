import type { MappingRow, RequiredTag } from '@/types/configApi'

/**
 * Client-side helpers for the Mappings tab (ADR-0013). The api validates; these only
 * group and shape rows for display.
 */

export interface TagGroup {
  key: string
  title: string
  tags: RequiredTag[]
}

/** Tags grouped by parameter in register order; machine-state tags last. */
export function groupTags(required: RequiredTag[]): TagGroup[] {
  const groups: TagGroup[] = []
  for (const tag of required) {
    const key = tag.parameterId ?? 'context'
    let group = groups.find((g) => g.key === key)
    if (!group) {
      group = { key, title: tag.parameterName ?? 'Machine state', tags: [] }
      groups.push(group)
    }
    group.tags.push(tag)
  }
  return groups.sort((a, b) => Number(a.key === 'context') - Number(b.key === 'context'))
}

export interface Place {
  topic: string
  field: string
}

export function placesFrom(rows: MappingRow[]): Record<string, Place> {
  return Object.fromEntries(rows.map((r) => [r.tag, { topic: r.topic, field: r.field ?? '' }]))
}

/** The rows a draft sends: required tags with a topic, in register order. */
export function rowsFrom(places: Record<string, Place>, required: RequiredTag[]): MappingRow[] {
  return required.flatMap((q) => {
    const p = places[q.tag]
    return p && p.topic.trim() ? [{ tag: q.tag, topic: p.topic, field: p.field.trim() || null }] : []
  })
}

/** "…/Volpak/Filler/SPC": the end of a long topic, for tight places; show the full one on hover. */
export function topicTail(topic: string, levels = 3): string {
  const parts = topic.split('/')
  return parts.length > levels ? `…/${parts.slice(-levels).join('/')}` : topic
}

/**
 * Topics the connection's filters imply for the register's machine areas: a filter
 * ".../Filler/#" and tags in SPC suggest ".../Filler/SPC". Filters without wildcards are topics.
 */
export function suggestTopics(subscriptions: string[], required: RequiredTag[]): string[] {
  const areas = [...new Set(required.map((r) => r.tag.split('.')[0]).filter((a): a is string => Boolean(a)))]
  const out = new Set<string>()
  for (const f of subscriptions) {
    if (f.endsWith('/#') && !f.includes('+')) {
      for (const area of areas) out.add(`${f.slice(0, -2)}/${area}`)
    } else if (!f.includes('#') && !f.includes('+')) {
      out.add(f)
    }
  }
  return [...out]
}

/** The part of a tag after its area, e.g. SetPointTemperatureVertical1: its field name by convention. */
export function tagLeaf(tag: string): string {
  return tag.split('.').slice(1).join('.')
}

