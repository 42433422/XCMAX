/**
 * 企业 Mod = 行业通用 Mod + 账号定制 Mod；AI 市场员工上岗后归属该栈（非游离 Mod）。
 */
import type { IndustryBaselinePlan } from '@/constants/platformShell'
import { isHostBridgeModId } from '@/constants/genericModPack'

export type EnterpriseModStack = {
  industryId: string
  industryModId: string | null
  industryLabel: string
  customModIds: string[]
  customLabels: Record<string, string>
  /** 行业包 + 定制 Mod id（企业 Mod 主体） */
  packageModIds: string[]
  /** 行业基础线 bridge / 可选宿主 Mod（员工运行载体） */
  hostLineModIds: string[]
  stackLabel: string
  stackShortLabel: string
}

/** 市场安装的独立员工 Mod；必须显式登记，避免任意 *-ai-employee 串栈 */
const WORKFLOW_CARRIER_MOD_IDS = new Set<string>([
  'wechat-contacts-ai-employee',
])

export function buildEnterpriseModStack(plan: IndustryBaselinePlan): EnterpriseModStack {
  const industryModIds = [...(plan.industry_mod_ids || [])]
  const customModIds = [...(plan.account_custom_mod_ids || [])]
  const packageModIds = [
    ...new Set([
      ...industryModIds,
      ...customModIds,
      ...(plan.custom_mod_ids || []).filter((id) => id && !customModIds.includes(id)),
    ]),
  ]

  const hostLineModIds = [
    ...new Set([...(plan.required_mod_ids || []), ...(plan.optional_mod_ids || [])]),
  ]

  const industryLabel =
    String(plan.industry_package?.product_name || '').trim() || plan.industry_id || '通用'
  const customLabels: Record<string, string> = {}
  for (const g of plan.groups || []) {
    if (g.id !== 'account_custom') continue
    for (const item of g.items || []) {
      if (item.mod_id) customLabels[item.mod_id] = item.label
    }
  }

  const customNames = customModIds.map((id) => customLabels[id] || id)
  const stackLabel = customNames.length
    ? `${industryLabel} + ${customNames.join(' + ')}`
    : industryLabel
  const stackShortLabel = customNames.length ? `${industryLabel}·定制` : industryLabel

  const industryModId =
    industryModIds[0] || String(plan.industry_package?.mod_id || '').trim() || null

  return {
    industryId: plan.industry_id,
    industryModId,
    industryLabel,
    customModIds,
    customLabels,
    packageModIds,
    hostLineModIds,
    stackLabel,
    stackShortLabel,
  }
}

export function isWorkflowCarrierModId(modId: string): boolean {
  const id = String(modId || '').trim()
  if (!id) return false
  if (WORKFLOW_CARRIER_MOD_IDS.has(id)) return true
  if (id.startsWith('xcagi-workflow-employee-')) return true
  return false
}

/** Mod 是否属于当前租户企业 Mod 栈（行业包 / 定制 / 基础线 / 工作流载体） */
export function modBelongsToEnterpriseStack(modId: string, stack: EnterpriseModStack): boolean {
  const id = String(modId || '').trim()
  if (!id) return false
  if (stack.packageModIds.includes(id)) return true
  if (stack.industryModId === id) return true
  if (stack.hostLineModIds.includes(id)) return true
  if (isHostBridgeModId(id)) return true
  return false
}

export function employeeBelongsToEnterpriseStack(
  hostModId: string | undefined | null,
  stack: EnterpriseModStack,
): boolean {
  return Boolean(hostModId && modBelongsToEnterpriseStack(hostModId, stack))
}

/** 市场员工包默认挂靠的企业 Mod（行业通用优先，无则基础线载体） */
export function defaultHostModIdForMarketEmployee(
  stack: EnterpriseModStack,
  catalogItem?: { host_mod_id?: string; enterprise_mod_id?: string },
): string {
  const explicit = String(
    catalogItem?.host_mod_id || catalogItem?.enterprise_mod_id || '',
  ).trim()
  if (explicit && modBelongsToEnterpriseStack(explicit, stack)) return explicit
  if (stack.customModIds.length === 1) return stack.customModIds[0]
  if (stack.industryModId) return stack.industryModId
  const carrier = stack.hostLineModIds.find((id) => isWorkflowCarrierModId(id))
  if (carrier) return carrier
  return stack.hostLineModIds[0] || stack.packageModIds[0] || ''
}
