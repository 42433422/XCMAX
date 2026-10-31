import { api } from './core'
import type { AgentRun } from './agentRuns'

export interface CatalogSource { source_id: string; epoch: string; protocol: string }
export interface CatalogObservation {
  source_key: string
  price: string
  period_start: string | null
  period_end: string | null
  period_label: string | null
  effective: boolean
}
export interface CatalogProduct {
  id: number
  name: string
  model_number: string
  /** Purchase unit/customer, never the denominator of a price. */
  unit: string
  price: string
  currency: string
  price_unit: string
  revision: string
  source: CatalogSource
  history: CatalogObservation[]
}
export interface CatalogEditRequest {
  operation_id: string
  revision: string
  action: 'append_price' | 'correct_price'
  price: string
  period_start: string | null
  period_end: string | null
  selected_sources: string[]
  reason: string
  confirmed: true
}
export interface CatalogRunResponse {
  success: boolean
  data?: AgentRun
  approval?: { run_id: string; step_id: string; tool_id: string; action: string; grant: string }
  operation?: { state: string; operation_id: string; request_digest: string; run_id: string }
}
export interface CatalogVerification {
  success: boolean
  data: { verified: boolean; outcome: 'saved' | 'rejected_no_effect'; reason_code?: string; receipt_kind?: 'catalog_preclaim_finalization_v1'; current_matches: boolean; historical_effect_verified: boolean; fresh_save: false; business_action_id: string; product: CatalogProduct; operation_id: string; run_id: string; request_digest: string }
}
const base = '/api/elt/owned-mixed-v1/products'
const scope = (mod: string) => {
  if (!mod.trim()) throw new Error('必须明确选择 Mod')
  return { headers: { 'X-XCAGI-Active-Mod-Id': mod } }
}
export const catalogPricesApi = {
  list: (keyword: string, mod: string) => api.get<{ success: boolean; data: CatalogProduct[]; source: CatalogSource; capability: string }>(base, { keyword }, scope(mod)),
  read: (id: number, mod: string) => api.get<{ success: boolean; data: CatalogProduct }>(`${base}/${id}`, {}, scope(mod)),
  submit: (id: number, body: CatalogEditRequest, mod: string) => api.post<CatalogRunResponse>(`${base}/${id}/edits`, body, scope(mod)),
  lookup: (operation: string, mod: string) => api.get<CatalogRunResponse>(`${base}/edits/${encodeURIComponent(operation)}`, {}, scope(mod)),
  verify: (operation: string, mod: string) => api.get<CatalogVerification>(`${base}/edits/${encodeURIComponent(operation)}/verification`, {}, scope(mod)),
  reconcile: (operation: string, mod: string) => api.post<CatalogVerification>(`${base}/edits/${encodeURIComponent(operation)}/reconciliation`, { confirmed: true }, scope(mod)),
}
