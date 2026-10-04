import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { NavLink } from 'react-router-dom'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useRoles } from '@/hooks/useAuth'
import { useEventCounts } from '@/hooks/useEventCounts'
import { useWorkflow } from '@/hooks/useWorkflow'
import { APP_IDENTITY, navSections, type NavItem } from '@/routes/navigation'
import { cn } from '@/utils/cn'

interface AppSidebarProps {
  collapsed: boolean
  onToggle: () => void
  /** Overlay mode drops the collapse control and always shows labels. */
  overlay?: boolean
  onNavigate?: () => void
}

export function AppSidebar({
  collapsed,
  onToggle,
  overlay = false,
  onNavigate,
}: AppSidebarProps) {
  const activeAlarmCount = useEventCounts()?.open ?? 0 // the open events, live
  const reasonCount = useWorkflow().waiting // what waits for this person (ADR-0025)
  const { has } = useRoles()
  const isCollapsed = overlay ? false : collapsed
  // Only the pages this account's roles can use (ADR-0016)
  const sections = navSections
    .map((section) => ({ ...section, items: section.items.filter((item) => !item.roles || has(...item.roles)) }))
    .filter((section) => section.items.length > 0)

  return (
    <div className="bg-nav flex h-full flex-col">
      {/* Brand */}
      <div
        className={cn(
          'border-nav-border flex h-14 shrink-0 items-center border-b',
          isCollapsed ? 'justify-center px-2' : 'gap-2.5 px-4',
        )}
      >
        <span className="bg-nav-accent/15 ring-nav-accent/30 grid size-8 shrink-0 place-items-center rounded-md ring-1">
          <CenterlineMark />
        </span>
        {!isCollapsed && (
          <div className="min-w-0">
            <p className="truncate text-[13px] leading-tight font-semibold text-white">
              {APP_IDENTITY.name}
            </p>
            <p className="text-nav-fg truncate text-[11px] leading-tight">
              {APP_IDENTITY.tagline}
            </p>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav
        className="flex-1 overflow-y-auto overflow-x-hidden py-3"
        aria-label="Main navigation"
      >
        {sections.map((section) => (
          <div key={section.label} className="mb-4 last:mb-0">
            {!isCollapsed && (
              <p className="text-nav-fg/70 px-4 pb-1.5 text-[10px] font-semibold tracking-[0.08em] uppercase">
                {section.label}
              </p>
            )}
            {isCollapsed && <div className="bg-nav-border mx-3 mb-2 h-px" />}

            <ul className={cn('flex flex-col gap-0.5', isCollapsed ? 'px-2' : 'px-2')}>
              {section.items.map((item) => (
                <li key={item.to}>
                  <SidebarNavItem
                    item={item}
                    collapsed={isCollapsed}
                    alarmCount={item.showAlarmCount ? activeAlarmCount : item.showReasonCount ? reasonCount : 0}
                    onNavigate={onNavigate}
                  />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="border-nav-border shrink-0 border-t p-2">
        {!overlay && (
          <button
            type="button"
            onClick={onToggle}
            className={cn(
              'text-nav-fg hover:bg-nav-hover focus-visible:ring-nav-accent flex h-9 w-full items-center rounded-md text-[13px] font-medium transition-colors hover:text-white focus-visible:ring-2 focus-visible:outline-none',
              isCollapsed ? 'justify-center' : 'gap-2.5 px-2.5',
            )}
            aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {isCollapsed ? (
              <PanelLeftOpen className="size-4.5 shrink-0" aria-hidden />
            ) : (
              <>
                <PanelLeftClose className="size-4.5 shrink-0" aria-hidden />
                Collapse
              </>
            )}
          </button>
        )}
        {!isCollapsed && (
          <p className="text-nav-fg/60 px-2.5 pt-2 pb-1 text-[10px]">
            {APP_IDENTITY.version}
          </p>
        )}
      </div>
    </div>
  )
}

function SidebarNavItem({
  item,
  collapsed,
  alarmCount,
  onNavigate,
}: {
  item: NavItem
  collapsed: boolean
  alarmCount: number
  onNavigate?: () => void
}) {
  const Icon = item.icon

  const link = (
    <NavLink
      to={item.to}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          'group relative flex h-10 items-center rounded-md text-[13px] font-medium transition-colors duration-150',
          'focus-visible:ring-nav-accent focus-visible:ring-2 focus-visible:outline-none',
          collapsed ? 'justify-center px-0' : 'gap-3 px-2.5',
          isActive
            ? 'bg-nav-active text-nav-fg-strong'
            : 'text-nav-fg hover:bg-nav-hover hover:text-white',
        )
      }
    >
      {({ isActive }) => (
        <>
          {/* Active rail — the accent edge marker, not a full-width fill. */}
          {isActive && (
            <span
              className="bg-nav-accent absolute inset-y-1.5 left-0 w-[3px] rounded-r"
              aria-hidden
            />
          )}
          <Icon className="size-4.5 shrink-0" aria-hidden />
          {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
          {alarmCount > 0 && (
            <span
              className={cn(
                'bg-critical-solid tnum grid place-items-center rounded-full font-semibold text-white',
                collapsed
                  ? 'absolute top-1 right-1 size-4 text-[10px]'
                  : 'h-5 min-w-5 px-1.5 text-[11px]',
              )}
            >
              {alarmCount}
            </span>
          )}
        </>
      )}
    </NavLink>
  )

  if (!collapsed) return link

  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right" sideOffset={10}>
        <p className="font-semibold">{item.label}</p>
        <p className="text-[11px] font-normal opacity-80">{item.description}</p>
      </TooltipContent>
    </Tooltip>
  )
}

function CenterlineMark() {
  return (
    <svg viewBox="0 0 24 24" className="size-4.5" aria-hidden>
      <path d="M2 12h20" stroke="#4ADE80" strokeWidth="1.75" strokeLinecap="round" />
      <path
        d="M2 16c3 0 3-8 6-8s3 11 6 11 3-8 6-8"
        fill="none"
        stroke="#60A5FA"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
