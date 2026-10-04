import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { mockApi } from '@/services/mockApi'
import type {
  Alarm,
  AlarmRow,
  CenterlineRow,
  Factory,
  Machine,
  ParameterDefinition,
  ParameterReading,
  ProcessSample,
  ProductionLine,
  SetpointChange,
  SetpointField,
  Sku,
  User,
} from '@/types'
import { buildAlarmRows, buildCenterlineRows, type PlantLookups } from '@/utils/selectors'

/** Fields the configuration modal can change, plus the audit reason. */
export interface ParameterConfigUpdate {
  readingId: string
  parameterId: string
  name: string
  unit: string
  minAllowed: number
  maxAllowed: number
  targetSetpoint: number
  hmiSetpoint: number
  warningTolerancePct: number
  criticalTolerancePct: number
  machineId: string
  skuId: string
  reason: string
}

export interface CenterlineContextValue {
  loading: boolean
  currentUser: User | null
  factories: Factory[]
  lines: ProductionLine[]
  machines: Machine[]
  skus: Sku[]
  parameters: ParameterDefinition[]
  readings: ParameterReading[]
  alarms: Alarm[]
  setpointHistory: SetpointChange[]
  samples: ProcessSample[]
  lookups: PlantLookups
  centerlineRows: CenterlineRow[]
  alarmRows: AlarmRow[]
  activeAlarmCount: number
  updateParameterConfig: (update: ParameterConfigUpdate) => number
  acknowledgeAlarm: (alarmId: string) => void
  resolveAlarm: (alarmId: string, note?: string) => void
  refresh: () => void
}

const CenterlineContext = createContext<CenterlineContextValue | null>(null)

export function CenterlineProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true)
  const [currentUser, setCurrentUser] = useState<User | null>(null)
  const [factories, setFactories] = useState<Factory[]>([])
  const [lines, setLines] = useState<ProductionLine[]>([])
  const [machines, setMachines] = useState<Machine[]>([])
  const [skus, setSkus] = useState<Sku[]>([])
  const [parameters, setParameters] = useState<ParameterDefinition[]>([])
  const [readings, setReadings] = useState<ParameterReading[]>([])
  const [alarms, setAlarms] = useState<Alarm[]>([])
  const [setpointHistory, setSetpointHistory] = useState<SetpointChange[]>([])
  const [samples, setSamples] = useState<ProcessSample[]>([])
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    void Promise.all([
      mockApi.getCurrentUser(),
      mockApi.getFactories(),
      mockApi.getProductionLines(),
      mockApi.getMachines(),
      mockApi.getSkus(),
      mockApi.getParameterDefinitions(),
      mockApi.getParameterReadings(),
      mockApi.getAlarms(),
      mockApi.getSetpointHistory(),
      mockApi.getProcessSamples(),
    ]).then(
      ([
        user,
        loadedFactories,
        loadedLines,
        loadedMachines,
        loadedSkus,
        loadedParameters,
        loadedReadings,
        loadedAlarms,
        loadedHistory,
        loadedSamples,
      ]) => {
        if (cancelled) return
        setCurrentUser(user)
        setFactories(loadedFactories)
        setLines(loadedLines)
        setMachines(loadedMachines)
        setSkus(loadedSkus)
        setParameters(loadedParameters)
        setReadings(loadedReadings)
        setAlarms(loadedAlarms)
        setSetpointHistory(loadedHistory)
        setSamples(loadedSamples)
        setLoading(false)
      },
    )

    return () => {
      cancelled = true
    }
  }, [reloadToken])

  const lookups = useMemo<PlantLookups>(
    () => ({ factories, lines, machines, skus, parameters }),
    [factories, lines, machines, skus, parameters],
  )

  const centerlineRows = useMemo(
    () => buildCenterlineRows(readings, lookups),
    [readings, lookups],
  )

  const alarmRows = useMemo(() => buildAlarmRows(alarms, lookups), [alarms, lookups])

  const activeAlarmCount = useMemo(
    () => alarms.filter((alarm) => alarm.status === 'active').length,
    [alarms],
  )

  /**
   * Applies a configuration edit to local state and records one history entry
   * per changed field. Returns the number of fields that actually changed so
   * the caller can word its confirmation toast accurately.
   */
  const updateParameterConfig = useCallback(
    (update: ParameterConfigUpdate): number => {
      const definition = parameters.find((p) => p.id === update.parameterId)
      const reading = readings.find((r) => r.id === update.readingId)
      if (!definition || !reading) return 0

      const changes: Array<{ field: SetpointField; previous: number; next: number }> = []
      const track = (field: SetpointField, previous: number, next: number) => {
        if (previous !== next) changes.push({ field, previous, next })
      }

      track('targetSetpoint', reading.targetSetpoint, update.targetSetpoint)
      track('hmiSetpoint', reading.hmiSetpoint, update.hmiSetpoint)
      track('minAllowed', definition.minAllowed, update.minAllowed)
      track('maxAllowed', definition.maxAllowed, update.maxAllowed)
      track(
        'warningTolerancePct',
        definition.warningTolerancePct,
        update.warningTolerancePct,
      )
      track(
        'criticalTolerancePct',
        definition.criticalTolerancePct,
        update.criticalTolerancePct,
      )

      setParameters((current) =>
        current.map((parameter) =>
          parameter.id === update.parameterId
            ? {
                ...parameter,
                name: update.name,
                unit: update.unit,
                minAllowed: update.minAllowed,
                maxAllowed: update.maxAllowed,
                warningTolerancePct: update.warningTolerancePct,
                criticalTolerancePct: update.criticalTolerancePct,
              }
            : parameter,
        ),
      )

      setReadings((current) =>
        current.map((item) =>
          item.id === update.readingId
            ? {
                ...item,
                targetSetpoint: update.targetSetpoint,
                hmiSetpoint: update.hmiSetpoint,
                updatedAt: new Date().toISOString(),
                updatedBy: currentUser?.name ?? 'Current user',
              }
            : item,
        ),
      )

      if (changes.length > 0) {
        const stamp = new Date().toISOString()
        const entries: SetpointChange[] = changes.map((change, index) => ({
          id: `sch-local-${Date.now()}-${index}`,
          parameterId: update.parameterId,
          machineId: update.machineId,
          skuId: update.skuId,
          field: change.field,
          previousValue: change.previous,
          newValue: change.next,
          unit: change.field.endsWith('TolerancePct') ? '%' : update.unit,
          reason: update.reason,
          changedBy: currentUser?.name ?? 'Current user',
          changedAt: stamp,
        }))
        setSetpointHistory((current) => [...entries, ...current])
      }

      return changes.length
    },
    [parameters, readings, currentUser],
  )

  const acknowledgeAlarm = useCallback(
    (alarmId: string) => {
      setAlarms((current) =>
        current.map((alarm) =>
          alarm.id === alarmId && alarm.status === 'active'
            ? {
                ...alarm,
                status: 'acknowledged',
                acknowledgedAt: new Date().toISOString(),
                acknowledgedBy: currentUser?.name ?? 'Current user',
              }
            : alarm,
        ),
      )
    },
    [currentUser],
  )

  const resolveAlarm = useCallback(
    (alarmId: string, note?: string) => {
      setAlarms((current) =>
        current.map((alarm) =>
          alarm.id === alarmId && alarm.status !== 'resolved'
            ? {
                ...alarm,
                status: 'resolved',
                resolvedAt: new Date().toISOString(),
                resolvedBy: currentUser?.name ?? 'Current user',
                resolutionNote: note ?? alarm.resolutionNote,
              }
            : alarm,
        ),
      )
    },
    [currentUser],
  )

  const refresh = useCallback(() => setReloadToken((token) => token + 1), [])

  const value = useMemo<CenterlineContextValue>(
    () => ({
      loading,
      currentUser,
      factories,
      lines,
      machines,
      skus,
      parameters,
      readings,
      alarms,
      setpointHistory,
      samples,
      lookups,
      centerlineRows,
      alarmRows,
      activeAlarmCount,
      updateParameterConfig,
      acknowledgeAlarm,
      resolveAlarm,
      refresh,
    }),
    [
      loading,
      currentUser,
      factories,
      lines,
      machines,
      skus,
      parameters,
      readings,
      alarms,
      setpointHistory,
      samples,
      lookups,
      centerlineRows,
      alarmRows,
      activeAlarmCount,
      updateParameterConfig,
      acknowledgeAlarm,
      resolveAlarm,
      refresh,
    ],
  )

  return (
    <CenterlineContext.Provider value={value}>{children}</CenterlineContext.Provider>
  )
}

export { CenterlineContext }
