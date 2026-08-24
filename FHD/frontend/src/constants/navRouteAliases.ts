/** 侧栏 view key → vue-router name（与 MainLayout 一致） */

import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'

export const SIDEBAR_ROUTE_ALIASES: Record<string, string> = {
  'approval-hub': 'approval-workspace',
  'mod-approval-hub': 'approval-workspace',
  'employee-workflow': 'workflow-employee-space',
  'erp-hr': 'attendance-employees',
  'mod-attendance-industry-home': 'attendance-industry-home',
  'mod-attendance-industry-settings': 'attendance-industry-settings',
  'mod-taiyangniao-pro-home': 'taiyangniao-pro-home',
  'mod-taiyangniao-pro-settings': 'taiyangniao-pro-settings',
}

export function resolveNavRouteName(viewKey: string, modPath?: string): string {
  const key = String(viewKey || '').trim()
  if (!key) return ''
  // 管理端「自治审批中心」走独立宿主页，避免撞上企业 ERP approval-workspace
  if (isAdminConsoleSpa() && (key === 'approval-hub' || key === 'mod-approval-hub')) {
    return 'autonomy-approval-hub'
  }
  const aliased = SIDEBAR_ROUTE_ALIASES[key]
  if (aliased) return aliased
  if (key.startsWith('mod-') && modPath) {
    const pathOnly = String(modPath).split('?')[0]?.split('#')[0] || ''
    if (pathOnly.includes('/approval-hub/workspace')) return 'approval-workspace'
    const lastSeg = pathOnly.split('/').filter(Boolean).pop()
    if (lastSeg) return lastSeg
  }
  return key
}
