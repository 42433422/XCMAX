import templateScopeRules from '@/shared/templateScopeRules.json'
import {
  resolveIndustryNavigationProfile,
  type IndustryBusinessMenuKey,
} from '@/constants/industryNavigationProfiles'

export type IndustryTemplateScopeKey =
  | 'orders'
  | 'shipmentRecords'
  | 'products'
  | 'materials'
  | 'customers'

export type IndustryTemplateScope = {
  key: IndustryTemplateScopeKey
  menuKey: IndustryBusinessMenuKey
  label: string
  templateType: string
  requiredTerms: string[]
  schemaSource: 'industry-subsystem' | 'generic-erp'
}

export type IndustryTemplateProfile = {
  industryId: string
  industryLabel: string
  categoryId: string
  categoryLabel: string
  scopes: IndustryTemplateScope[]
}

type TemplateRule = {
  label?: string
  templateType?: string
  requiredTerms?: string[]
}

const BASE_TEMPLATE_RULES = templateScopeRules as Record<string, TemplateRule>

const SCOPE_BY_MENU_KEY: Partial<Record<IndustryBusinessMenuKey, IndustryTemplateScopeKey>> = {
  products: 'products',
  materials: 'materials',
  customers: 'customers',
  orders: 'orders',
  'shipment-records': 'shipmentRecords',
}

const SUBSYSTEM_KEY_BY_SCOPE: Record<IndustryTemplateScopeKey, string> = {
  products: 'products',
  materials: 'materials',
  customers: 'customers',
  orders: 'orders',
  shipmentRecords: 'shipment-records',
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function firstRecord(...values: unknown[]): Record<string, unknown> {
  return values.map(asRecord).find((value) => Object.keys(value).length > 0) || {}
}

function resolveSubsystems(currentConfig: unknown): Record<string, unknown> {
  const root = asRecord(currentConfig)
  const config = asRecord(root.config)
  const industry = asRecord(root.industry)
  const industryConfig = asRecord(industry.config)
  return firstRecord(root.subsystems, config.subsystems, industry.subsystems, industryConfig.subsystems)
}

function resolveSubsystemTerms(subsystem: Record<string, unknown>): string[] {
  const fields = Array.isArray(subsystem.fields) ? subsystem.fields : []
  return fields
    .map((field) => String(asRecord(field).label || '').trim())
    .filter((label, index, labels) => Boolean(label) && labels.indexOf(label) === index)
}

function normalizeTemplateLabel(value: unknown, fallback: string): string {
  const label = String(value || '').trim()
  return label || fallback
}

/**
 * 模板目录与行业侧栏使用同一个真实能力骨架。
 * 只有已映射到宿主 ERP 页面且具备模板创建/导出语义的菜单才会进入模板库；
 * 行业 Mod 若声明 subsystems.fields，则字段词条直接来自该真实 schema。
 */
export function resolveIndustryTemplateProfile(industryId: string, currentConfig?: unknown): IndustryTemplateProfile {
  const navigation = resolveIndustryNavigationProfile(industryId)
  const subsystems = resolveSubsystems(currentConfig)
  const industryDefinesSubsystemSchema = Object.keys(subsystems).length > 0
  const scopes: IndustryTemplateScope[] = []
  const usedScopes = new Set<IndustryTemplateScopeKey>()

  for (const menuKey of navigation.previewMenuKeys) {
    const scopeKey = SCOPE_BY_MENU_KEY[menuKey as IndustryBusinessMenuKey]
    if (!scopeKey || usedScopes.has(scopeKey)) continue

    const baseRule = BASE_TEMPLATE_RULES[scopeKey] || {}
    const subsystem = asRecord(subsystems[SUBSYSTEM_KEY_BY_SCOPE[scopeKey]])
    const subsystemTerms = resolveSubsystemTerms(subsystem)
    // 行业包已经声明 schema 时，不为未声明的子系统套用通用字段冒充行业模板。
    if (industryDefinesSubsystemSchema && subsystemTerms.length === 0) continue
    const fallbackLabel = normalizeTemplateLabel(baseRule.label, scopeKey)
    const navigationLabel = normalizeTemplateLabel(navigation.menuLabels[menuKey], fallbackLabel)
    const label = normalizeTemplateLabel(subsystem.label, navigationLabel)
    const templateType = normalizeTemplateLabel(subsystem.entity, label)

    scopes.push({
      key: scopeKey,
      menuKey: menuKey as IndustryBusinessMenuKey,
      label,
      templateType,
      requiredTerms: subsystemTerms.length > 0
        ? subsystemTerms
        : [...(Array.isArray(baseRule.requiredTerms) ? baseRule.requiredTerms : [])],
      schemaSource: subsystemTerms.length > 0 ? 'industry-subsystem' : 'generic-erp',
    })
    usedScopes.add(scopeKey)
  }

  const normalizedIndustryId = String(industryId || '').trim()
  const categorySelectedDirectly = normalizedIndustryId === navigation.categoryId
  return {
    industryId: normalizedIndustryId || navigation.id,
    industryLabel: categorySelectedDirectly ? navigation.categoryLabel : normalizedIndustryId || navigation.categoryLabel,
    categoryId: navigation.categoryId,
    categoryLabel: navigation.categoryLabel,
    scopes,
  }
}

export function buildIndustryTemplateScopeConfig(profile: IndustryTemplateProfile): Record<string, TemplateRule> {
  return Object.fromEntries(profile.scopes.map((scope) => [scope.key, {
    label: scope.label,
    templateType: scope.templateType,
    requiredTerms: [...scope.requiredTerms],
  }]))
}
