import { Cable, ClipboardList, CloudOff, Eye, Ruler, Scale, Send, Tags, TriangleAlert, Waypoints } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { EmptyState } from '@/components/shared/EmptyState'
import { PageHeader } from '@/components/shared/PageHeader'
import { HistorianConnectionCard } from '@/components/setup/HistorianConnectionCard'
import { MqttConnectionCard } from '@/components/setup/MqttConnectionCard'
import { NotificationsConnectionCard } from '@/components/setup/NotificationsConnectionCard'
import { ParameterEditor } from '@/components/setup/ParameterEditor'
import { MappingsTab } from '@/components/setup/mappings/MappingsTab'
import { RangesTab } from '@/components/setup/ranges/RangesTab'
import { RoutingTab } from '@/components/setup/routing/RoutingTab'
import { RulesTab } from '@/components/setup/rules/RulesTab'
import { RecentChanges, TagRegister } from '@/components/setup/TagRegister'
import { WorkflowQuestionsCard } from '@/components/setup/WorkflowQuestionsCard'
import { monitorValues } from '@/components/setup/liveValues'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useRoles } from '@/hooks/useAuth'
import { configApi } from '@/services/configApi'
import { monitoringApi } from '@/services/monitoringApi'
import type { Connections, LatestValue, RegisterParameter, RegisterView } from '@/types/configApi'

type Tab = 'connections' | 'tags' | 'mappings' | 'rules' | 'notifications' | 'workflow' | 'ranges'
const TABS: Tab[] = ['connections', 'tags', 'mappings', 'rules', 'notifications', 'workflow', 'ranges']

const message = (caught: unknown) => (caught instanceof Error ? caught.message : String(caught))

/** A tab the account can see but not change (ADR-0016). */
function ReadOnly({ what, role }: { what: string; role: string }) {
  return (
    <p className="border-line bg-surface-muted text-ink-soft mb-4 flex items-center gap-2 rounded-lg border px-4 py-2 text-[13px]">
      <Eye className="size-4 shrink-0" aria-hidden /> You can see {what}; changing them needs the {role} role.
    </p>
  )
}

/**
 * Configuration (ADR-0011, ADR-0012, ADR-0023, ADR-0029): the data-source and notification connections,
 * the tag register, the monitoring rules, who gets notified and the Analytics-valid ranges. Secrets go to the api and are never shown again; every
 * register and rules change is checked, versioned and audited in the database.
 * Managers and Administrators see every tab; the Rules tab is the Manager's to change,
 * the others the Administrator's (ADR-0016).
 */
export function ConfigurationSetupPage() {
  const { isManager, isAdministrator } = useRoles()
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab')
  const tab: Tab = TABS.includes(requested as Tab) ? (requested as Tab) : 'connections'
  const [connections, setConnections] = useState<Connections | null>(null)
  const [register, setRegister] = useState<RegisterView | null>(null)
  const [historian, setLatest] = useState<Record<string, LatestValue | null>>({})
  const [live, setLive] = useState<Record<string, LatestValue>>({})
  // monitor-core's values off MQTT win: live, and there even away from the plant (the simulator); Timebase fills the rest
  const latest = useMemo(() => ({ ...historian, ...live }), [historian, live])
  const [editing, setEditing] = useState<RegisterParameter | null>(null)
  const [connectionsError, setConnectionsError] = useState<string | null>(null)
  const [registerError, setRegisterError] = useState<string | null>(null)

  const loadLatest = useCallback((view: RegisterView) => {
    const tags = view.parameters.flatMap((p) => p.zones.flatMap((z) => [z.setpoint, z.actual])).filter((t): t is string => Boolean(t))
    if (tags.length === 0) return
    configApi
      .latest(tags)
      .then((r) => setLatest(r.values))
      .catch(() => setLatest({}))
  }, [])

  useEffect(() => {
    configApi
      .connections()
      .then(setConnections)
      .catch((caught: unknown) => setConnectionsError(message(caught)))
    configApi
      .register()
      .then((r) => {
        setRegister(r)
        loadLatest(r)
      })
      .catch((caught: unknown) => setRegisterError(message(caught)))
  }, [loadLatest])

  // monitor-core's values, every 5 s while the page is open: the Tags and Rules tabs show the HMI as it is now
  useEffect(() => {
    if (!register) return
    const controller = new AbortController()
    const load = () => {
      if (document.visibilityState !== 'visible') return
      monitoringApi
        .live(controller.signal)
        .then((view) => setLive(monitorValues(register, view)))
        .catch((caught: unknown) => {
          if (!(caught instanceof DOMException && caught.name === 'AbortError')) setLive({})
        })
    }
    load()
    const timer = window.setInterval(load, 5000)
    return () => {
      controller.abort()
      window.clearInterval(timer)
    }
  }, [register])

  const unavailable = (what: string, detail: string) => (
    <div className="bg-surface border-critical-border shadow-card rounded-lg border">
      <EmptyState icon={CloudOff} title={`Can't load ${what}`} description={detail} />
    </div>
  )

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Configuration"
        description="Where Centerline gets its data, which tags belong to each parameter and zone, where they arrive on MQTT, the rules it judges them by, who gets notified, and which values count in Analytics."
        breadcrumbs={[{ label: 'Setup' }, { label: 'Configuration' }]}
      />

      <Tabs value={tab} onValueChange={(v) => setParams(v === 'connections' ? {} : { tab: v }, { replace: true })}>
        <TabsList>
          <TabsTrigger value="connections">
            <Cable className="size-4" aria-hidden /> Connections
          </TabsTrigger>
          <TabsTrigger value="tags">
            <Tags className="size-4" aria-hidden /> Tags
          </TabsTrigger>
          <TabsTrigger value="mappings">
            <Waypoints className="size-4" aria-hidden /> Mappings
          </TabsTrigger>
          <TabsTrigger value="rules">
            <Scale className="size-4" aria-hidden /> Rules
          </TabsTrigger>
          <TabsTrigger value="notifications">
            <Send className="size-4" aria-hidden /> Notifications
          </TabsTrigger>
          <TabsTrigger value="workflow">
            <ClipboardList className="size-4" aria-hidden /> Reasons
          </TabsTrigger>
          <TabsTrigger value="ranges">
            <Ruler className="size-4" aria-hidden /> Analytics ranges
          </TabsTrigger>
        </TabsList>

        <TabsContent value="connections" className="mt-4">
          {!isAdministrator && <ReadOnly what="the connections" role="Administrator" />}
          {connectionsError ? (
            unavailable('the connections', connectionsError)
          ) : connections ? (
            <fieldset disabled={!isAdministrator} className="contents">
              <div className="grid grid-cols-1 items-start gap-4 2xl:grid-cols-2">
                <MqttConnectionCard connection={connections.mqtt} onSaved={setConnections} />
                <HistorianConnectionCard connection={connections.historian} onSaved={setConnections} />
                <NotificationsConnectionCard connection={connections.notifications} onSaved={setConnections} />
              </div>
            </fieldset>
          ) : (
            <Skeleton className="h-[520px] w-full rounded-lg" />
          )}
        </TabsContent>

        <TabsContent value="tags" className="mt-4">
          {!isAdministrator && <ReadOnly what="the tag register" role="Administrator" />}
          {registerError ? (
            unavailable('the register', registerError)
          ) : register ? (
            <div className="flex flex-col gap-4">
              {register.fileWarning && (
                <p className="border-warning-border bg-warning-surface text-ink flex items-start gap-2 rounded-lg border px-4 py-2.5 text-[13px]">
                  <TriangleAlert className="text-warning mt-0.5 size-4 shrink-0" aria-hidden /> {register.fileWarning}
                </p>
              )}
              <TagRegister view={register} latest={latest} onEdit={isAdministrator ? setEditing : undefined} />
              <RecentChanges entries={register.audit} />
            </div>
          ) : (
            <Skeleton className="h-[520px] w-full rounded-lg" />
          )}
        </TabsContent>

        <TabsContent value="mappings" className="mt-4">
          {!isAdministrator && <ReadOnly what="the mappings" role="Administrator" />}
          {registerError ? unavailable('the mappings', registerError) : <MappingsTab canEdit={isAdministrator} />}
        </TabsContent>

        <TabsContent value="rules" className="mt-4">
          {!isManager && <ReadOnly what="the rules" role="Manager" />}
          {registerError ? (
            unavailable('the rules', registerError)
          ) : register ? (
            <RulesTab register={register} latest={latest} canEdit={isManager} />
          ) : (
            <Skeleton className="h-[520px] w-full rounded-lg" />
          )}
        </TabsContent>

        <TabsContent value="notifications" className="mt-4">
          {!isAdministrator && <ReadOnly what="who gets notified" role="Administrator" />}
          <RoutingTab canEdit={isAdministrator} />
        </TabsContent>

        <TabsContent value="workflow" className="mt-4">
          {!isAdministrator && <ReadOnly what="the follow-up questions" role="Administrator" />}
          <WorkflowQuestionsCard canEdit={isAdministrator} />
        </TabsContent>

        <TabsContent value="ranges" className="mt-4">
          {!isAdministrator && <ReadOnly what="the Analytics ranges" role="Administrator" />}
          <RangesTab canEdit={isAdministrator} />
        </TabsContent>
      </Tabs>

      {register && editing && (
        <ParameterEditor
          key={`${editing.id}-${register.version}`}
          parameter={editing}
          version={register.version}
          onClose={() => setEditing(null)}
          onSaved={(view) => {
            setRegister(view)
            setEditing(null)
            loadLatest(view)
          }}
        />
      )}
    </div>
  )
}
