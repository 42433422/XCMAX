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

/** 登录/切换租户/登出后，重载按 tenant 隔离的客户端持久化 store。 */
export function refreshTenantScopedClientStores(input?: TenantStorageScopeInput): void {
  invalidateTenantStorageScopeCache()
  const scope = resolveTenantStorageScope(input)
  setTenantStorageScopeCache(scope)
  try {
    useWorkflowAiEmployeesStore().reloadForTenantScope(scope)
  } catch {
    /* pinia 未就绪 */
  }
  void hydrateWorkspacePrefsFromServer(scope).then(() => {
    try {
      useWorkflowAiEmployeesStore().reloadForTenantScope(scope)
    } catch {
      /* pinia 未就绪 */
    }
  })
  try {
    useWorkflowEmployeeSpaceStore().reloadForTenantScope(scope)
  } catch {
    /* pinia 未就绪 */
  }
  try {
    useModsStore().reloadActiveModForTenantScope(scope)
  } catch {
    /* pinia 未就绪 */
  }
}
