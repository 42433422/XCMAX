import type { TenantStorageScopeInput } from '@/utils/tenantStorageScope'

/** 由 accountProfile 写入：当前已登录会话的服务端身份（优先于 localStorage 市场 JSON）。 */
let runtimeScopeInput: TenantStorageScopeInput | null = null

export function setRuntimeTenantStorageScopeInput(input: TenantStorageScopeInput | null): void {
  runtimeScopeInput = input
}

export function getRuntimeTenantStorageScopeInput(): TenantStorageScopeInput | null {
  return runtimeScopeInput
}
