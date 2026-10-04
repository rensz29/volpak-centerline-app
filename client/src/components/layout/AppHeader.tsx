import { Menu } from 'lucide-react'

import { NotificationBell } from '@/components/layout/NotificationBell'
import { UserMenu } from '@/components/layout/UserMenu'

interface AppHeaderProps {
  onOpenMobileNav: () => void
}

/** The bar above every page. The app is the Volpak line: the prototype's plant selectors are gone. */
export function AppHeader({ onOpenMobileNav }: AppHeaderProps) {
  return (
    <header className="bg-nav border-nav-border sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b px-3 sm:px-4">
      <button
        type="button"
        onClick={onOpenMobileNav}
        className="text-nav-fg hover:bg-nav-hover focus-visible:ring-nav-accent grid size-9 shrink-0 place-items-center rounded-md transition-colors hover:text-white focus-visible:ring-2 focus-visible:outline-none lg:hidden"
        aria-label="Open navigation"
      >
        <Menu className="size-5" aria-hidden />
      </button>

      <div className="flex-1" />

      <NotificationBell />

      <span className="bg-nav-border h-6 w-px shrink-0" aria-hidden />

      <UserMenu />
    </header>
  )
}
