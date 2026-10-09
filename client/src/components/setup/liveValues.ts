import type { LatestValue, RegisterView } from '@/types/configApi'
import type { LiveView } from '@/types/monitoringApi'

/**
 * monitor-core's latest values off MQTT, by tag: what the HMI shows now, from the plant broker or, away from the
 * plant, the simulator (deploy/compose.sim.yaml). None while monitor-core isn't running or has no broker connection.
 * The Configuration page prefers them to Timebase's, which lag behind and can't be reached off the plant network.
 */
export function monitorValues(view: RegisterView, live: LiveView): Record<string, LatestValue> {
  const out: Record<string, LatestValue> = {}
  const m = live.monitor
  if (!m?.alive || !m.connected) return out
  const zones = new Map(live.parameters.flatMap((p) => p.zones.map((z) => [z.channel, z] as const)))
  for (const p of view.parameters) {
    for (const z of p.zones) {
      const lz = zones.get(`${p.id}.${z.id}`)
      for (const [tag, v] of [[z.setpoint, lz?.setpoint], [z.actual, lz?.actual]] as const) {
        const n = v === null || v === undefined ? Number.NaN : Number(v)
        if (tag && Number.isFinite(n)) out[tag] = { value: n, quality: 192, at: m.beatAt }
      }
    }
  }
  return out
}
