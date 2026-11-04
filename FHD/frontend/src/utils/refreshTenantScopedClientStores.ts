import {
  invalidateTenantStorageScopeCache,
  resolveTenantStorageScope,
  setTenantStorageScopeCache,
  type TenantStorageScopeInput,
} from '@/utils/tenantStorageScope'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { useWorkflowEmployeeSpaceStore } from '@/stores/workflowEmployeeSpace'
import { useModsStore } from '@/stores/mods'
import { hydrateWorkspacePrefsFromServer } from '@/utils/workspacePrefsApi'
import { refreshHostPackAcknowledged } from '@/constants/productFlow'
import { productReadAccountEpoch, updateProductReadAccountScope } from './productReadAccountScope'

/**
 * 登录/切换租户/登出后，重载按 tenant 隔离的客户端持久化 store。
 *
 * The returned promise represents the local workspace-preference hydration.
 * Router guards await it so retained tenant-scoped state is available before
 * deciding whether the host onboarding is really required.
 */
function reloadScopedStore(reload: () => void): void {
  try { reload() } catch { /* pinia 未就绪 */ }
}

export async function refreshTenantScopedClientStores(input?: TenantStorageScopeInput, hydrate = true): Promise<void> {
  let scope = resolveTenantStorageScope(input)
  // A concurrent login/refresh can bump the scope generation while prefs load.
  // Retry once, then adopt the generation this call just wrote instead of aborting.
  for (let attempt = 0; attempt < 2; attempt++) {
    updateProductReadAccountScope(input)
    const epoch = productReadAccountEpoch.value
    invalidateTenantStorageScopeCache()
    scope = resolveTenantStorageScope(input)
    setTenantStorageScopeCache(scope)
    reloadScopedStore(() => useWorkflowAiEmployeesStore().reloadForTenantScope(scope))
    if (hydrate) await hydrateWorkspacePrefsFromServer(scope)
    if (epoch === productReadAccountEpoch.value) break
  }
  // Workspace preferences can write tenant-scoped localStorage in this same
  // document.  The browser emits no `storage` event to its writing document,
  // so refresh the reactive sidebar acknowledgement explicitly.
  refreshHostPackAcknowledged()
  reloadScopedStore(() => useWorkflowAiEmployeesStore().reloadForTenantScope(scope))
  reloadScopedStore(() => useWorkflowEmployeeSpaceStore().reloadForTenantScope(scope))
  reloadScopedStore(() => useModsStore().reloadActiveModForTenantScope(scope))
}
