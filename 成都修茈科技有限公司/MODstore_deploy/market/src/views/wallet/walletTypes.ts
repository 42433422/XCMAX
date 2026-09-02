/** WalletView 拆分共用的类型与纯常量（自 WalletView.vue 原样迁移） */
import type { CatalogProviderBlock } from '../../llmMedia'
import type {
  LlmBillingSettings,
  LlmModelPricing,
} from '../../composables/useLlmPricingDisplay'

/** 与后端 llm_model_taxonomy.CATEGORY_ORDER 一致 */
export const LLM_CATEGORY_ORDER = ['llm', 'vlm', 'image', 'video', 'other']

export interface TransactionRecord {
  id: string | number
  created_at?: string | null
  type?: string | null
  amount: number
  description?: string
  order_no?: string
  refund_no?: string
}

export interface RawTransactionRecord extends Omit<TransactionRecord, 'amount'> {
  amount?: unknown
}

export interface RefundRecord {
  id: string | number
  refund_no?: string
  order_no?: string
  amount?: number | string
  status?: string | null
}

export interface PlanRecord {
  name?: string
  expires_at?: string | null
}

export interface QuotaRecord {
  quota_type: string
  remaining?: number
  total?: number
}

export interface LlmCapability {
  l3_status?: string
  l1_status?: string
  platform_billing_ok?: boolean
  [key: string]: unknown
}

export interface WalletLlmModelRow {
  id: string
  category?: string
  capability?: LlmCapability
  pricing?: LlmModelPricing
}

export interface WalletCatalogProvider extends CatalogProviderBlock {
  provider: string
  label: string
  models: string[]
  models_detailed?: WalletLlmModelRow[]
  error?: string | null
  fetch_source?: string | null
  fetched_at?: string | null
}

export interface WalletCatalog {
  providers: WalletCatalogProvider[]
  category_labels?: Record<string, string>
  billing_settings?: LlmBillingSettings
  gate_hints?: {
    platform_catalog_gate?: boolean
    byok_catalog_gate?: boolean
    platform_require_priced?: boolean
  }
  preferences?: { provider?: string; model?: string }
  fernet_configured?: boolean
  cache_ttl_seconds?: number
}

export interface LlmStatusRecord {
  provider: string
  label?: string
  has_user_override?: boolean
  has_platform_key?: boolean
  masked_key?: string
}

export interface BareCredentialResponse {
  provider?: string
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
