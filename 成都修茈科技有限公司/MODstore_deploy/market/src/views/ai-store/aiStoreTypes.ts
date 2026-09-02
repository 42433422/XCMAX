// 拆分自 AiStoreView.vue：类型、文案映射与纯函数（逻辑逐字迁移，行为不变）。
import { employeePackRole, type EmployeePackIconKind } from '../../constants/officeEmployeePack'

export type StoreNavId = 'all' | 'host_foundation' | 'office' | 'office_aux' | 'workflow' | 'ai_employee'

export const ARTIFACT_LABELS = {
  mod: 'MOD 插件',
  employee_pack: 'AI 员工包',
  bundle: '资源包',
  surface: '界面扩展',
  workflow_template: '工作流模板',
}

export const MATERIAL_CATEGORY_LABELS = {
  ai_employee: 'AI 员工',
  agent_prompt: 'Agent 提示词',
  skill: 'Skill',
  tts_voice: 'TTS 声音模型',
  mod_asset: 'MOD 包素材',
  page_style: '页面风格',
  personal_design: '个性化设计',
  workflow_template: '工作流模板',
  other: '其他素材',
}

export const LICENSE_SCOPE_LABELS = {
  personal: '个人使用',
  commercial: '商业授权',
  free_personal: '免费个人用',
  enterprise: '企业级',
}

export const COMPLIANCE_STATUS_LABELS = {
  approved: '已审核',
  under_review: '投诉处理中',
  restricted: '已降权',
  delisted: '已下架',
}

export const SECURITY_LABELS = {
  personal: '个人',
  team: '团队',
  enterprise: '企业级',
  confidential: '保密',
}

export interface AiStoreItem {
  id: number | string
  pkg_id?: string
  name?: string
  version?: string
  industry?: string
  artifact?: string
  material_category?: string
  material_category_label?: string
  license_scope?: string
  license_scope_label?: string
  security_level?: string
  compliance_status?: string
  purchased?: boolean
  favorited?: boolean
  favorite_count?: number
  description?: string
  price: number
}

export interface CatalogFacets {
  industries: string[]
  artifacts: string[]
  material_categories: string[]
  license_scopes: string[]
  security_levels: string[]
}

export interface StoreNavTab {
  id: StoreNavId
  label: string
  icon: EmployeePackIconKind | undefined
  badge: string
}

export interface AiStoreDisplayGroup {
  key: string
  title: string
  kind: EmployeePackIconKind | undefined
  items: AiStoreItem[]
}

export function artifactLabel(art: string | undefined): string {
  return (art && (ARTIFACT_LABELS as Record<string, string>)[art]) || art || '其他'
}

export function materialCategoryLabel(cat: string | undefined): string {
  return (cat && (MATERIAL_CATEGORY_LABELS as Record<string, string>)[cat]) || cat || '其他素材'
}

export function licenseScopeLabel(scope: string | undefined): string {
  return (scope && (LICENSE_SCOPE_LABELS as Record<string, string>)[scope]) || scope || '个人使用'
}

export function complianceStatusLabel(status: string | undefined): string {
  return (status && (COMPLIANCE_STATUS_LABELS as Record<string, string>)[status]) || status || '待处理'
}

export function securityLabel(level: string | undefined): string {
  return (level && (SECURITY_LABELS as Record<string, string>)[level]) || '个人'
}

export function securityLevelClass(level: string | undefined): string {
  if (level === 'confidential') return 'tag-confidential'
  if (level === 'enterprise') return 'tag-enterprise'
  return 'tag-personal'
}

export function truncate(str: string | undefined | null, len: number): string {
  if (!str) return ''
  return str.length > len ? str.slice(0, len) + '…' : str
}

export function formatSocialCount(n?: number) {
  const v = Number(n ?? 0) || 0
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万`
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`
  return String(v)
}

export function employeeRoleLabel(pkgId?: string) {
  return employeePackRole(pkgId)
}

export function customerServiceLink(item: AiStoreItem, scene = 'complaint') {
  return {
    name: 'customer-service',
    query: {
      scene,
      catalog_id: String(item?.id || ''),
      pkg_id: item?.pkg_id || '',
      item_name: item?.name || '',
      material_category: item?.material_category || '',
    },
  }
}
