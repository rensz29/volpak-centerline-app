import { CloudOff, Loader2, ShieldX } from 'lucide-react'
import { Suspense, lazy, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { AuthFrame } from '@/components/auth/AuthFrame'
import { IdleWarning } from '@/components/auth/IdleWarning'
import { MaintenanceWatch } from '@/components/maintenance/MaintenanceWatch'
import { AppLayout } from '@/components/layout/AppLayout'
import { EmptyState } from '@/components/shared/EmptyState'
import { ChartSkeleton } from '@/components/shared/LoadingSkeleton'
import { Button } from '@/components/ui/button'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AuthProvider } from '@/context/AuthContext'
import { EventCountsProvider } from '@/context/EventCountsContext'
import { WorkflowProvider } from '@/context/WorkflowContext'
import { useAuth, useRoles } from '@/hooks/useAuth'
import { AccountsPage } from '@/pages/AccountsPage'
import { ChangePasswordPage } from '@/pages/ChangePasswordPage'
import { ConfigurationSetupPage } from '@/pages/ConfigurationSetupPage'
import { EventHistoryPage } from '@/pages/EventHistoryPage'
import { LiveCenterlinePage } from '@/pages/LiveCenterlinePage'
import { MaintenancePage } from '@/pages/MaintenancePage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { NotificationsPage } from '@/pages/NotificationsPage'
import { OcapLibraryPage } from '@/pages/OcapLibraryPage'
import { OpenEventsPage } from '@/pages/OpenEventsPage'
import { ReasonsPage } from '@/pages/ReasonsPage'
import { SignInPage } from '@/pages/SignInPage'
import { ROUTES } from '@/routes/navigation'
import type { Role } from '@/types/authApi'

// ECharts is large, so the Analytics page and its charts load only when visited.
const AnalyticsCorrelationPage = lazy(() =>
  import('@/pages/AnalyticsCorrelationPage').then((m) => ({ default: m.AnalyticsCorrelationPage })),
)

const PRIVILEGED: Role[] = ['MANAGER', 'ADMINISTRATOR']

/** A page for some roles only (ADR-0016). The api refuses the others anyway; this says so plainly. */
function Only({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { has } = useRoles()
  if (has(...roles)) return <>{children}</>
  return (
    <div className="bg-surface border-line shadow-card rounded-lg border">
      <EmptyState icon={ShieldX} title="Not for your role"
                  description={`This page is for the ${roles.map((r) => r[0] + r.slice(1).toLowerCase()).join(' or ')} role.`} />
    </div>
  )
}

function SignedInApp() {
  const { isAdministrator } = useRoles()
  return (
    <EventCountsProvider>
      <WorkflowProvider>
        <Routes>
          <Route element={<AppLayout />}>
            {/* Digital Centerline is the working home of the application. */}
            <Route index element={<Navigate to={ROUTES.centerline} replace />} />
            {/* The prototype's plant overview is gone: the app is the Volpak line (ADR-0019) */}
            <Route path={ROUTES.overview} element={<Navigate to={ROUTES.centerline} replace />} />
            <Route path={ROUTES.centerline} element={<LiveCenterlinePage />} />
            <Route
              path={ROUTES.analytics}
              element={
                <Only roles={PRIVILEGED}>
                  <Suspense fallback={<ChartSkeleton height={460} />}>
                    <AnalyticsCorrelationPage />
                  </Suspense>
                </Only>
              }
            />
            <Route path={ROUTES.activeAlarms} element={<OpenEventsPage />} />
            <Route path={ROUTES.alarmHistory} element={<EventHistoryPage />} />
            <Route path={ROUTES.reasons} element={<ReasonsPage />} />
            <Route path={ROUTES.ocaps} element={<OcapLibraryPage />} />
            <Route path={ROUTES.configuration} element={<Only roles={PRIVILEGED}><ConfigurationSetupPage /></Only>} />
            <Route path={ROUTES.accounts} element={<Only roles={['ADMINISTRATOR']}><AccountsPage /></Only>} />
            <Route path={ROUTES.maintenance} element={<Only roles={PRIVILEGED}><MaintenancePage /></Only>} />
            <Route path={ROUTES.notifications} element={<Only roles={PRIVILEGED}><NotificationsPage /></Only>} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
        <IdleWarning />
        {isAdministrator && <MaintenanceWatch />}
      </WorkflowProvider>
    </EventCountsProvider>
  )
}

/** Nothing but signing in until there's a session; a temporary password is changed first (IAM-03). */
function Gate() {
  const { state, retry } = useAuth()
  switch (state.status) {
    case 'loading':
      return (
        <main className="bg-canvas grid min-h-screen place-items-center">
          <Loader2 className="text-ink-muted size-6 animate-spin" aria-label="Loading" />
        </main>
      )
    case 'unreachable':
      return (
        <AuthFrame title="Can't reach Centerline" description={state.problem.message}>
          <p className="text-ink-soft flex items-start gap-2 text-[13px]">
            <CloudOff className="mt-0.5 size-4 shrink-0" aria-hidden /> Nobody can sign in until the api and its database answer.
          </p>
          <Button type="button" size="sm" className="mt-4" onClick={retry}>
            Try again
          </Button>
        </AuthFrame>
      )
    case 'signed-out':
      return <SignInPage reason={state.reason} />
    case 'signed-in':
      return state.info.user.mustChange ? <ChangePasswordPage /> : <SignedInApp />
  }
}

export default function App() {
  return (
    <AuthProvider>
      <TooltipProvider delayDuration={300}>
        <Gate />
        <Toaster />
      </TooltipProvider>
    </AuthProvider>
  )
}
