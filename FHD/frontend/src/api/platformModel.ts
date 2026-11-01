import { api } from './core'

export const PLATFORM_MODEL_CHANGED_EVENT = 'xcagi:platform-model-changed'
export const PLATFORM_MODEL_CHANGED_KEY = 'xcagi_platform_model_changed'
export function notifyPlatformModelChanged(): void {
  window.dispatchEvent(new Event(PLATFORM_MODEL_CHANGED_EVENT))
  try { localStorage.setItem(PLATFORM_MODEL_CHANGED_KEY, String(Date.now())) } catch { /* same-tab event still refreshes */ }
}

export interface PlatformModelConfig {
  provider: string
  label: string
  base_url: string
  model: string
  display_name: string
  has_key: boolean
  masked_key: string
  source: 'stored' | 'environment' | 'none'
  is_default: boolean
  revision: string | null
}

export interface PlatformModelScope {
  default_provider: string | null
  effective_scope: string
  scope_description: string
  byok_policy: string
}

export interface PlatformModelList extends PlatformModelScope {
  ok: boolean
  encryption_ready: boolean
  providers: PlatformModelConfig[]
}

export interface PlatformModelDraft {
  base_url: string
  model: string
  display_name: string
  api_key?: string
  make_default: boolean
  expected_revision: string | null
}

export interface PlatformModelSaved extends PlatformModelScope {
  ok: boolean
  config: Omit<PlatformModelConfig, 'label'> & { label?: string }
}

export interface PlatformModelTest {
  ok: boolean
  tested_model: string
  latency_ms: number
}

const path = '/api/xcmax/market-proxy/llm/admin/platform-model-config'
const providerPath = (provider: string) => `${path}/${encodeURIComponent(provider)}`

export const platformModelApi = {
  list: (signal?: AbortSignal) => api.get<PlatformModelList>(path, {}, { signal, timeoutMs: 15_000, cache: 'no-store' }),
  save: (provider: string, draft: PlatformModelDraft, signal?: AbortSignal) =>
    api.put<PlatformModelSaved>(providerPath(provider), draft, { signal, timeoutMs: 20_000 }),
  test: (provider: string, draft: PlatformModelDraft, signal?: AbortSignal) =>
    api.post<PlatformModelTest>(`${providerPath(provider)}/test`, draft, { signal, timeoutMs: 35_000 }),
}
