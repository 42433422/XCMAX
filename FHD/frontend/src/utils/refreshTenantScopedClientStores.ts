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
import { updateProductReadAccountScope } from './productReadAccountScope'

/**
 * 登录/切换租户/登出后，重载按 tenant 隔离的客户端持久化 store。
 *
 * The returned promise represents the local workspace-preference hydration.
 * Router guards await it so retained tenant-scoped state is available before
 * deciding whether the host onboarding is really required.
 */
export async function refreshTenantScopedClientStores(input?: TenantStorageScopeInput): Promise<void> {
  updateProductReadAccountScope(input)
  invalidateTenantStorageScopeCache()
  const scope = resolveTenantStorageScope(input)
  setTenantStorageScopeCache(scope)
  try {
    useWorkflowAiEmployeesStore().reloadForTenantScope(scope)
  } catch {
    /* pinia 未就绪 */
  }
  await hydrateWorkspacePrefsFromServer(scope)
  // Workspace preferences can write tenant-scoped localStorage in this same
  // document.  The browser emits no `storage` event to its writing document,
  // so refresh the reactive sidebar acknowledgement explicitly.
  refreshHostPackAcknowledged()
  try {
    useWorkflowAiEmployeesStore().reloadForTenantScope(scope)
  } catch {
    /* pinia 未就绪 */
  }
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
