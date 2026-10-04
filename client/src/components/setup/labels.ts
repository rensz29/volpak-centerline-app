import type { ParameterStatus } from '@/types/configApi'

export const STATUS_LABELS: Record<ParameterStatus, string> = {
  active: 'Monitored',
  analytics_only: 'Analytics only',
  awaiting_tag: 'Not used yet',
}

export const STATUS_HELP: Record<ParameterStatus, string> = {
  active: 'Monitored for HMI mismatch and Warning/Critical, and available in Analytics. Every zone needs a setpoint and an actual tag.',
  analytics_only: 'Available in Analytics only. Every zone needs an actual tag; setpoints are optional.',
  awaiting_tag: 'Kept in the register but not monitored or analysed, e.g. while tags are still being published.',
}
