import { resolveApprovalPagePath, resolveApprovalPageRedirectForRouteName } from '@/utils/approvalPagePaths'
import { resolveErpPagePath, resolveErpPageRedirectForRouteName } from '@/utils/erpPagePaths'
import { resolveLanPagePath, resolveLanPageRedirectForRouteName } from '@/utils/lanPagePaths'
import {
  resolvePlannerPagePath,
  resolvePlannerPageRedirectForRouteName,
} from '@/utils/plannerPagePaths'
import {
  resolveCustomerServicePagePath,
  resolveCustomerServicePageRedirectForRouteName,
} from '@/utils/customerServicePagePaths'
import {
  resolveModelPaymentPagePath,
  resolveModelPaymentPageRedirectForRouteName,
} from '@/utils/modelPaymentPagePaths'
import {
  resolveOfficeEmployeePagePath,
  resolveOfficeEmployeePageRedirectForRouteName,
} from '@/utils/officeEmployeePagePaths'
import { resolveWorkflowPageRedirectForRouteName } from '@/utils/workflowPagePaths'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'

/** 将宿主业务 path 映射为 Mod 页（若已启用对应 Mod 页面门面） */
export function resolveHostBusinessPagePath(hostPath: string): string {
  if (isAdminConsoleSpa()) return hostPath.startsWith('/') ? hostPath : `/${hostPath}`
  let p = resolveErpPagePath(hostPath)
  if (p !== hostPath) return p
  p = resolveApprovalPagePath(hostPath)
  if (p !== hostPath) return p
  p = resolveModelPaymentPagePath(hostPath)
  if (p !== hostPath) return p
  p = resolveLanPagePath(hostPath)
  if (p !== hostPath) return p
  p = resolvePlannerPagePath(hostPath)
  if (p !== hostPath) return p
  p = resolveOfficeEmployeePagePath(hostPath)
  if (p !== hostPath) return p
  return resolveCustomerServicePagePath(hostPath)
}

/** 平台壳守卫：宿主业务 route name → Mod 全路径 */
export function resolveHostBusinessPageRedirect(routeName: string): string | null {
  // 管理端经 HostModBridgeView 加载 Mod 视图，侧栏走宿主 route name（/internal-customer-service 等）
  if (isAdminConsoleSpa()) return null
  return (
    resolveErpPageRedirectForRouteName(routeName) ||
    resolveApprovalPageRedirectForRouteName(routeName) ||
    resolveModelPaymentPageRedirectForRouteName(routeName) ||
    resolveLanPageRedirectForRouteName(routeName) ||
    resolvePlannerPageRedirectForRouteName(routeName) ||
    resolveOfficeEmployeePageRedirectForRouteName(routeName) ||
    resolveWorkflowPageRedirectForRouteName(routeName) ||
    resolveCustomerServicePageRedirectForRouteName(routeName)
  )
}
