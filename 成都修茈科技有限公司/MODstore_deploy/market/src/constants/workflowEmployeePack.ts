/** MOD 商店「工作流员工」合集：6 个独立工作流员工 Mod（各 manifest 仅 1 条 workflow_employees）。 */

export const WORKFLOW_EMPLOYEE_PKG_IDS = [
  'xcagi-workflow-employee-label-print',
  'xcagi-workflow-employee-shipment-mgmt',
  'xcagi-workflow-employee-receipt-confirm',
  'xcagi-workflow-employee-wechat-msg',
  'xcagi-workflow-employee-wechat-phone',
  'xcagi-workflow-employee-real-phone',
] as const

export const WORKFLOW_EMPLOYEE_COLLECTION = 'workflow_employee'

export function isWorkflowEmployeePkg(pkgId?: string | null): boolean {
  return WORKFLOW_EMPLOYEE_PKG_IDS.includes((pkgId || '') as (typeof WORKFLOW_EMPLOYEE_PKG_IDS)[number])
}
