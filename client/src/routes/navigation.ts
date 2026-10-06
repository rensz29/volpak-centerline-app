import {
  Activity,
  BellRing,
  BookOpen,
  ClipboardList,
  GitCompareArrows,
  History,
  Send,
  Settings2,
  UsersRound,
  Wrench,
  type LucideIcon,
} from 'lucide-react'

import type { Role } from '@/types/authApi'

export interface NavItem {
  label: string
  to: string
  icon: LucideIcon
  description: string
  /** Renders the live active-alarm count as a badge on the nav item. */
  showAlarmCount?: boolean
  /** Renders how many reasons wait for this person (ADR-0025). */
  showReasonCount?: boolean
  /** Only these roles see it (ADR-0016); the api checks them anyway. Absent: every role. */
  roles?: Role[]
}

export interface NavSection {
  label: string
  items: NavItem[]
}

export const ROUTES = {
  overview: '/overview',
  centerline: '/centerline',
  analytics: '/analytics',
  activeAlarms: '/alarms/active',
  alarmHistory: '/alarms/history',
  configuration: '/configuration',
  accounts: '/accounts',
  maintenance: '/maintenance',
  notifications: '/notifications',
  reasons: '/reasons',
  ocaps: '/ocaps',
} as const

export const navSections: NavSection[] = [
  {
    label: 'Monitoring',
    items: [
      {
        label: 'Digital Centerline',
        to: ROUTES.centerline,
        icon: Activity,
        description: 'Target, HMI setpoint and actual for every zone, judged live by monitor-core',
      },
      {
        label: 'Analytics & Correlation',
        to: ROUTES.analytics,
        icon: GitCompareArrows,
        description: 'Correlate actual values and setpoints from Timebase history',
        roles: ['MANAGER', 'ADMINISTRATOR'],
      },
    ],
  },
  {
    label: 'Alarms',
    items: [
      {
        label: 'Active Alarms',
        to: ROUTES.activeAlarms,
        icon: BellRing,
        description: 'Every open event, Criticals first; a Manager acknowledges a Critical',
        showAlarmCount: true,
      },
      {
        label: 'Alarm History',
        to: ROUTES.alarmHistory,
        icon: History,
        description: 'Every closed event, filtered; Managers and Administrators export it as CSV',
      },
      {
        label: 'Reasons',
        to: ROUTES.reasons,
        icon: ClipboardList,
        description: "Each HMI mismatch asks the shift's operator why; Managers guide",
        showReasonCount: true,
      },
      {
        label: 'OCAP Library',
        to: ROUTES.ocaps,
        icon: BookOpen,
        description: 'The out-of-control action plans offered after a reason; Managers upload and activate them',
      },
      {
        label: 'Notifications',
        to: ROUTES.notifications,
        icon: Send,
        description: 'Every message to Teams and email, with each attempt; Administrators send TEST messages and re-drive failures',
        roles: ['MANAGER', 'ADMINISTRATOR'],
      },
    ],
  },
  {
    label: 'Setup',
    items: [
      {
        label: 'Configuration',
        to: ROUTES.configuration,
        icon: Settings2,
        description: 'Connections, tags, their MQTT places and the monitoring rules',
        roles: ['MANAGER', 'ADMINISTRATOR'],
      },
      {
        label: 'Maintenance',
        to: ROUTES.maintenance,
        icon: Wrench,
        description: 'Windows when nothing is judged on the line or on chosen zones',
        roles: ['MANAGER', 'ADMINISTRATOR'],
      },
      {
        label: 'Accounts',
        to: ROUTES.accounts,
        icon: UsersRound,
        description: 'Who can sign in, with which roles',
        roles: ['ADMINISTRATOR'],
      },
    ],
  },
]

/** Product identity, kept in one place so branding is a single-line change. */
export const APP_IDENTITY = {
  name: 'Digital Centerline',
  tagline: 'Production Intelligence',
  shortName: 'DC',
  version: 'v0.1.0 · Phase 1 prototype',
} as const
