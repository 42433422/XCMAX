import { ref } from 'vue'
import type { TenantStorageScopeInput } from './tenantStorageScope'
import { getRuntimeTenantStorageScopeInput } from './tenantStorageScopeRuntime'

// An epoch distinguishes A → B → A; comparing only the final account ID cannot retire A's old reads.
export const productReadAccountEpoch = ref(0)
let accountKey = ''
export function productReadScopeKey(activeModId: string): string {
  return JSON.stringify([productReadAccountEpoch.value, getRuntimeTenantStorageScopeInput(), activeModId])
}
export function updateProductReadAccountScope(input?: TenantStorageScopeInput): void {
  const key = JSON.stringify([input?.tenantId ?? null, input?.marketUserId ?? null,
    input?.localUserId ?? null, input?.marketUsername ?? '', input?.accountKind ?? ''])
  if (key === accountKey) return
  accountKey = key
  productReadAccountEpoch.value++
}
