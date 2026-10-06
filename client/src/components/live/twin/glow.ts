import type { Tone } from '../liveModel'

/** The status tones on the navy line view (ADR-0033): the `-glow` tokens read on navy as the others do on white. */
export const GLOW: Record<Tone, { text: string; dot: string; border: string; soft: string }> = {
  normal: { text: 'text-normal-glow', dot: 'bg-normal-glow', border: 'border-normal-glow/35', soft: 'bg-normal-glow/10' },
  warning: { text: 'text-warning-glow', dot: 'bg-warning-glow', border: 'border-warning-glow/55', soft: 'bg-warning-glow/10' },
  critical: { text: 'text-critical-glow', dot: 'bg-critical-glow', border: 'border-critical-glow/65', soft: 'bg-critical-glow/10' },
  nodata: { text: 'text-nodata-glow', dot: 'bg-nodata-glow', border: 'border-white/10', soft: 'bg-white/[0.04]' },
  brand: { text: 'text-nav-accent', dot: 'bg-nav-accent', border: 'border-nav-accent/50', soft: 'bg-nav-accent/10' },
}
