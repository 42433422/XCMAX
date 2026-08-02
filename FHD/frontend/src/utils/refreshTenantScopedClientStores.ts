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

/**
 * 登录/切换租户/登出后，重载按 tenant 隔离的客户端持久化 store。
 *
 * 返回的 Promise 只等待本机后端的 workspace 偏好回填；路由在已验证会话后
 * await 它，才能避免升级后 tenant scoped localStorage 尚未恢复时误进宿主入门。
 */
export async function refreshTenantScopedClientStores(input?: TenantStorageScopeInput): Promise<void> {
  invalidateTenantStorageScopeCache()
  const scope = resolveTenantStorageScope(input)
  setTenantStorageScopeCache(scope)
  try {
    useWorkflowAiEmployeesStore().reloadForTenantScope(scope)
  } catch {
    /* pinia 未就绪 */
  }
  await hydrateWorkspacePrefsFromServer(scope)
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
