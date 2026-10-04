import { Activity } from 'lucide-react'
import type { ReactNode } from 'react'

import { APP_IDENTITY } from '@/routes/navigation'

/** The full-page frame for signing in and for the forced password change. */
export function AuthFrame({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <main className="bg-canvas flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-[420px]">
        <div className="mb-5 flex items-center justify-center gap-2.5">
          <span className="bg-nav grid size-9 place-items-center rounded-lg text-white">
            <Activity className="size-5" aria-hidden />
          </span>
          <span>
            <span className="text-ink block text-[15px] leading-tight font-semibold">{APP_IDENTITY.name}</span>
            <span className="text-ink-muted block text-[12px] leading-tight">{APP_IDENTITY.tagline}</span>
          </span>
        </div>
        <section className="bg-surface border-line shadow-card rounded-xl border px-6 py-6">
          <h1 className="text-ink text-[18px] font-semibold">{title}</h1>
          {description && <div className="text-ink-soft mt-1 text-[13px]">{description}</div>}
          <div className="mt-5">{children}</div>
        </section>
      </div>
    </main>
  )
}
