import { useState } from 'react'
import { Outlet } from 'react-router-dom'

import { ShiftWarning } from '@/components/auth/ShiftWarning'
import { AppHeader } from '@/components/layout/AppHeader'
import { AppSidebar } from '@/components/layout/AppSidebar'
import { StorageBanner } from '@/components/layout/StorageBanner'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { ReasonAssistant } from '@/components/workflow/ReasonAssistant'
import { useRoles } from '@/hooks/useAuth'
import { useLocalStorage } from '@/hooks/useLocalStorage'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { cn } from '@/utils/cn'

export function AppLayout() {
  const [collapsed, setCollapsed] = useLocalStorage('dc.sidebar.collapsed', false)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const { isOperator } = useRoles()

  const isDesktop = useMediaQuery('(min-width: 1024px)')
  const isNarrowDesktop = useMediaQuery('(max-width: 1279px)')

  // On narrow desktops the icon rail buys back meaningful table width, so it
  // collapses automatically. The user's own choice still wins on wide screens.
  const effectiveCollapsed = collapsed || isNarrowDesktop

  // Derived rather than reset in an effect: growing past the breakpoint simply
  // stops the overlay from being open, with no intermediate render.
  const overlayOpen = mobileNavOpen && !isDesktop

  return (
    <div className="bg-canvas flex min-h-screen">
      {/* Persistent sidebar — desktop only */}
      <aside
        className={cn(
          'sticky top-0 hidden h-screen shrink-0 transition-[width] duration-200 ease-out lg:block',
          effectiveCollapsed ? 'w-16' : 'w-64',
        )}
      >
        <AppSidebar
          collapsed={effectiveCollapsed}
          onToggle={() => setCollapsed(!collapsed)}
        />
      </aside>

      {/* Overlay sidebar — tablet and below */}
      <Sheet open={overlayOpen} onOpenChange={setMobileNavOpen}>
        <SheetContent
          side="left"
          className="w-[264px] border-none p-0 sm:max-w-[264px] [&>button]:text-nav-fg [&>button]:hover:bg-nav-hover [&>button]:hover:text-white"
        >
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <AppSidebar
            collapsed={false}
            overlay
            onToggle={() => undefined}
            onNavigate={() => setMobileNavOpen(false)}
          />
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <AppHeader onOpenMobileNav={() => setMobileNavOpen(true)} />
        <ShiftWarning />
        <StorageBanner />

        <main className="min-w-0 flex-1">
          <div className="mx-auto w-full max-w-[1800px] p-4 sm:p-5 lg:p-6">
            <Outlet />
          </div>
        </main>
      </div>
      {/* The operator's reason assistant, on every page (ADR-0040) */}
      {isOperator && <ReasonAssistant />}
    </div>
  )
}
