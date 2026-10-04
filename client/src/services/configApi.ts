import type {
  Connections,
  HistorianCheck,
  HistorianForm,
  HistorianTag,
  LatestValue,
  MappingCheck,
  MappingDiscovery,
  MappingDraft,
  MappingImport,
  MappingsOverview,
  MappingVersion,
  MqttCheck,
  MqttForm,
  ParameterUpdate,
  RegisterView,
  RulesCheck,
  RulesDraft,
  RulesOverview,
  RulesProposal,
  RulesVersion,
} from '@/types/configApi'

import { json, request } from './http'

/** Configuration page calls. No login exists yet: the api must stay on 127.0.0.1 (ADR-0011). */
export const configApi = {
  connections(): Promise<Connections> {
    return request<Connections>('/api/v1/config/connections')
  },

  saveHistorian(form: HistorianForm): Promise<Connections> {
    return request<Connections>('/api/v1/config/connections/historian', json('PUT', historianBody(form)))
  },

  testHistorian(form: HistorianForm): Promise<HistorianCheck> {
    return request<HistorianCheck>('/api/v1/config/connections/historian/test', json('POST', historianBody(form)))
  },

  saveMqtt(form: MqttForm): Promise<Connections> {
    return request<Connections>('/api/v1/config/connections/mqtt', json('PUT', mqttBody(form)))
  },

  testMqtt(form: MqttForm, seconds: number): Promise<MqttCheck> {
    return request<MqttCheck>('/api/v1/config/connections/mqtt/test', json('POST', { ...mqttBody(form), seconds }))
  },

  tags(q = ''): Promise<{ namespace: string; total: number; tags: HistorianTag[] }> {
    return request(`/api/v1/config/historian/tags?q=${encodeURIComponent(q)}&limit=500`)
  },

  latest(tags: string[]): Promise<{ values: Record<string, LatestValue | null>; missing: string[] }> {
    return request('/api/v1/config/historian/latest', json('POST', { tags }))
  },

  register(): Promise<RegisterView> {
    return request<RegisterView>('/api/v1/config/register')
  },

  saveParameter(id: string, update: ParameterUpdate): Promise<RegisterView> {
    return request<RegisterView>(`/api/v1/config/register/parameters/${encodeURIComponent(id)}`, json('PUT', update))
  },

  // Monitoring rules (ADR-0012)

  rules(): Promise<RulesOverview> {
    return request<RulesOverview>('/api/v1/config/rules')
  },

  rulesProposal(): Promise<RulesProposal> {
    return request<RulesProposal>('/api/v1/config/rules/proposal')
  },

  rulesVersion(number: number): Promise<RulesVersion> {
    return request<RulesVersion>(`/api/v1/config/versions/${number}`)
  },

  checkRules(draft: RulesDraft, signal?: AbortSignal): Promise<RulesCheck> {
    return request<RulesCheck>('/api/v1/config/versions/check', json('POST', draft, signal))
  },

  saveRules(draft: RulesDraft): Promise<RulesOverview> {
    return request<RulesOverview>('/api/v1/config/versions', json('POST', draft))
  },

  activateRules(number: number, body: { expectedActive: number | null; at: string | null; reason: string }): Promise<RulesOverview> {
    return request<RulesOverview>(`/api/v1/config/versions/${number}/activate`, json('POST', body))
  },

  cancelActivation(id: string, reason: string): Promise<RulesOverview> {
    return request<RulesOverview>(`/api/v1/config/activations/${encodeURIComponent(id)}/cancel`, json('POST', { reason }))
  },

  addSku(code: string, name: string, reason: string): Promise<RulesOverview> {
    return request<RulesOverview>('/api/v1/config/skus', json('POST', { code, name, reason }))
  },

  renameSku(code: string, name: string, reason: string): Promise<RulesOverview> {
    return request<RulesOverview>(`/api/v1/config/skus/${encodeURIComponent(code)}`, json('PUT', { name, reason }))
  },

  // Tag mappings (ADR-0013)

  mappings(): Promise<MappingsOverview> {
    return request<MappingsOverview>('/api/v1/config/mappings')
  },

  mappingVersion(number: number): Promise<MappingVersion> {
    return request<MappingVersion>(`/api/v1/config/mappings/versions/${number}`)
  },

  mappingCsvUrl(number: number): string {
    return `/api/v1/config/mappings/versions/${number}/export.csv`
  },

  checkMapping(draft: MappingDraft, signal?: AbortSignal): Promise<MappingCheck> {
    return request<MappingCheck>('/api/v1/config/mappings/versions/check', json('POST', draft, signal))
  },

  saveMapping(draft: MappingDraft): Promise<MappingsOverview> {
    return request<MappingsOverview>('/api/v1/config/mappings/versions', json('POST', draft))
  },

  activateMapping(number: number, body: { expectedActive: number | null; at: string | null; reason: string }): Promise<MappingsOverview> {
    return request<MappingsOverview>(`/api/v1/config/mappings/versions/${number}/activate`, json('POST', body))
  },

  cancelMappingActivation(id: string, reason: string): Promise<MappingsOverview> {
    return request<MappingsOverview>(`/api/v1/config/mappings/activations/${encodeURIComponent(id)}/cancel`, json('POST', { reason }))
  },

  importMapping(format: 'topic-map' | 'csv', content: string): Promise<MappingImport> {
    return request<MappingImport>('/api/v1/config/mappings/import', json('POST', { format, content }))
  },

  discoverMapping(seconds: number): Promise<MappingDiscovery> {
    return request<MappingDiscovery>('/api/v1/config/mappings/discover', json('POST', { seconds }))
  },

  deleteSku(code: string, reason: string): Promise<RulesOverview> {
    return request<RulesOverview>(`/api/v1/config/skus/${encodeURIComponent(code)}?reason=${encodeURIComponent(reason)}`, {
      method: 'DELETE',
    })
  },
}

function historianBody(f: HistorianForm) {
  return {
    baseUrl: f.baseUrl,
    dataset: f.dataset,
    timeoutS: f.timeoutS,
    verifyTls: f.verifyTls,
    authType: f.authType,
    username: f.username,
    token: f.token || null,
    password: f.password || null,
    reason: f.reason,
  }
}

function mqttBody(f: MqttForm) {
  return {
    host: f.host,
    port: f.port,
    protocol: f.protocol,
    tlsEnabled: f.tlsEnabled,
    verifyHostname: f.verifyHostname,
    caPem: f.caPem || null,
    clearCa: f.clearCa,
    username: f.username,
    password: f.password || null,
    clearPassword: f.clearPassword,
    clientId: f.clientId,
    keepaliveS: f.keepaliveS,
    subscriptions: f.subscriptions,
    freshnessS: f.freshnessS,
    reason: f.reason,
  }
}
