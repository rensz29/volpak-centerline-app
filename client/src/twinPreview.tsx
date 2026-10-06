// TEMPORARY visual check of the line view with fixture data; deleted after the check.
import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { LineView } from '@/components/live/LineView'
import type { LiveView, LiveZone } from '@/types/monitoringApi'
import './index.css'

const params = new URLSearchParams(location.search)
const mode = params.get('mode') ?? 'mixed'
const t0 = Date.now()
const iso = (ms: number) => new Date(ms).toISOString()

function zone(id: string, name: string, channel: string, sp: number, act: number, extra: Partial<LiveZone> = {}): LiveZone {
  const w = channel.startsWith('P09') ? 0.3 : 5
  return {
    id, name, channel, known: mode !== 'down', setpoint: String(sp), actual: act.toFixed(1), target: String(sp),
    bands: { warnLow: String(sp - w), warnHigh: String(sp + w), critLow: String(sp - 2 * w), critHigh: String(sp + 2 * w) },
    hmi: 'AT_TARGET', actualSeverity: 'NORMAL', actualPending: null, hmiRulesVersion: 3, actualRulesVersion: 3, control: null, events: [],
    ...extra,
  }
}

function fixture(): LiveView {
  const mixed = mode === 'mixed'
  return {
    serverTime: iso(Date.now()),
    monitor: mode === 'down' ? { instance: 'x', startedAt: iso(t0), beatAt: iso(t0 - 90000), ageS: 90, alive: false }
      : { instance: 'x', startedAt: iso(t0), beatAt: iso(Date.now()), ageS: 1, alive: true, judging: true, stop: mode === 'stopped' ? 'stopped' : 'running', rulesVersion: 3, mappingVersion: 2, registerVersion: '2026-10-05.1' },
    parameters: [
      { id: 'P02', name: 'Vertical Temperature', unit: '°C', zones: [1, 2, 3, 4, 5, 6].map((i) => zone(`V${i}`, `Vertical ${i}`, `P02.V${i}`, 180, 180 + (i % 3) * 0.4,
        mixed && i === 4 ? { actual: '186.2', actualSeverity: 'WARNING', actualEvent: 'e-warn', events: ['e-warn'] }
          : mixed && i === 6 ? { control: { state: 'off', since: iso(t0 - 3600000), by: 'szyrelle', reason: 'Heater element replaced, checking' } } : {})) },
      { id: 'P03', name: 'Bottom Temperature', unit: '°C', zones: [zone('FRONT', 'Front bottom', 'P03.FRONT', 170, 170.3), zone('REAR', 'Rear bottom', 'P03.REAR', 170, 169.8)] },
      { id: 'P04', name: 'Top Temperature', unit: '°C', zones: [zone('FRONT', 'Front top 1', 'P04.FRONT', 175, 175.2),
        zone('REAR', 'Rear top 1', 'P04.REAR', 175, mixed ? 187.4 : 175.1, mixed ? { actualSeverity: 'CRITICAL', actualEvent: 'e-crit', events: ['e-crit'] } : {})] },
      { id: 'P06', name: 'Discharge Point', unit: null, zones: [zone('N1', 'Nozzle 1', 'P06.N1', 98, 98),
        zone('N2', 'Nozzle 2', 'P06.N2', 98, 98, mixed ? { setpoint: '103', hmi: 'PENDING', hmiDue: iso(Date.now() + 42000) } : {}), zone('N3', 'Nozzle 3', 'P06.N3', 98, 98)] },
      { id: 'P09', name: 'Pressure', unit: 'bar', zones: [zone('MAIN', 'Dosing pressure', 'P09.MAIN', 2.5, 2.52)] },
    ],
    events: [],
    counts: { zones: 14, hmiOpen: 0, warning: mixed ? 1 : 0, critical: mixed ? 1 : 0 },
    control: { serverTime: iso(Date.now()), switchedOff: [], maintenance: [] },
  }
}

function Preview() {
  const [view, setView] = useState(fixture)
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = setInterval(() => { setView(fixture()); setNow(Date.now()) }, 2000)
    return () => clearInterval(t)
  }, [])
  return (
    <div className="bg-canvas min-h-screen p-6">
      <LineView view={view} now={now} onOpenEvent={(id) => console.log('open', id)} />
    </div>
  )
}

createRoot(document.getElementById('root')!).render(<StrictMode><Preview /></StrictMode>)
