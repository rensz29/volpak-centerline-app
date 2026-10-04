/**
 * Asia/Manila display helpers (ANA-20): the api queries and computes in UTC,
 * the page shows Manila time. Manila is UTC+8 with no daylight saving, so a
 * fixed offset converts exactly.
 */

const MANILA_OFFSET_MS = 8 * 3600 * 1000

/** Epoch ms → "YYYY-MM-DDTHH:mm", the value of a datetime-local input showing Manila time. */
export function toManilaInput(epochMs: number): string {
  return new Date(epochMs + MANILA_OFFSET_MS).toISOString().slice(0, 16)
}

/** A datetime-local value read as Manila time → epoch ms, or null when incomplete. */
export function fromManilaInput(value: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value)
  if (!match) return null
  const [, y, mo, d, h, mi] = match.map(Number) as [number, number, number, number, number, number]
  return Date.UTC(y, mo - 1, d, h, mi) - MANILA_OFFSET_MS
}

export function toUtcIso(epochMs: number): string {
  return new Date(epochMs).toISOString().replace(/\.\d{3}Z$/, 'Z')
}

const dateTimeFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Manila',
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

const fullFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Manila',
  year: 'numeric',
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

/** "28 Sep, 14:05" in Manila time, for axis labels. */
export function formatManilaShort(epochMs: number): string {
  return dateTimeFormat.format(epochMs)
}

/** "28 Sep 2026, 14:05:00" in Manila time, for tooltips. */
export function formatManilaFull(epochMs: number): string {
  return fullFormat.format(epochMs)
}

const timeFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Manila',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

/** "14:05:07" in Manila time, for times within an event. */
export function formatManilaTime(epochMs: number): string {
  return timeFormat.format(epochMs)
}

/** "4 min 38 s", "2.5 h", for durations in data-quality notes. */
export function formatDuration(seconds: number): string {
  const s = Math.abs(seconds)
  if (s < 120) return `${Math.round(s)} s`
  if (s < 7200) return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`
  return `${(s / 3600).toFixed(1)} h`
}
