import templateScopeRules from '@/shared/templateScopeRules.json'

export interface TemplateScopeMeta {
  label: string
  templateType: string
  requiredTerms: string[]
}

/** 业务范围配置：沿用原视图引用的 @/shared/templateScopeRules.json */
export const TEMPLATE_SCOPE_CONFIG = templateScopeRules as unknown as Record<string, TemplateScopeMeta>

/** 词条等价别名表：校验必备词条时按归一化后的别名集合匹配 */
export const TERM_EQUIVALENTS: Record<string, string[]> = {
  '产品型号': ['产品型号', '型号', '产品编码'],
  '型号': ['型号', '产品型号', '产品编码'],
  '规格': ['规格', '规格型号', '规格/kg'],
  '规格型号': ['规格型号', '规格', '规格/kg'],
  '价格': ['价格', '单价', '单价/元'],
  '单价': ['单价', '价格', '单价/元'],
  '金额': ['金额', '金额/元', '金额合计', '总金额', '金额总计'],
  '数量': ['数量', '数量(kg)', '数量/kg', '数量/件', '数量/桶', '库存数量'],
  '电话': ['电话', '联系电话', '手机号'],
  '购买单位': ['购买单位', '单位', '单位名称', '客户名称', '厂名'],
  '客户名称': ['客户名称', '购买单位', '单位名称', '厂名'],
  '金额总计': ['金额总计', '金额合计', '总金额', '金额', '合计金额'],
  '金额合计': ['金额合计', '金额总计', '总金额', '金额', '合计金额'],
  '销售金额': ['销售金额', '销售额', '销售总额', '营业额'],
  '实收款': ['实收款', '实收', '已收款', '实收金额'],
  '下欠款金额': ['下欠款金额', '下欠款', '欠款', '应收余额', '欠款金额']
}

export function normalizeTerm(value: unknown): string {
  return String(value || '').replace(/\s+/g, '').trim().toLowerCase()
}

export function getScopeMeta(scopeKey: unknown): TemplateScopeMeta | null {
  const key = String(scopeKey || '').trim()
  if (!key) return null
  if (Object.prototype.hasOwnProperty.call(TEMPLATE_SCOPE_CONFIG, key)) {
    return TEMPLATE_SCOPE_CONFIG[key]
  }
  if (key === 'custom') {
    return { label: '自定义', templateType: '自定义模板', requiredTerms: [] }
  }
  return null
}

export function isKnownScopeKey(scopeKey: unknown): boolean {
  const key = String(scopeKey || '').trim()
  if (!key) return false
  return Object.prototype.hasOwnProperty.call(TEMPLATE_SCOPE_CONFIG, key) || key === 'custom'
}

export function getRequiredTermsByScope(scopeKey: unknown): string[] {
  const meta = getScopeMeta(scopeKey)
  return meta ? (Array.isArray(meta.requiredTerms) ? meta.requiredTerms : []) : []
}

export function getScopeIconClass(scopeKey: unknown): string {
  const iconMap: Record<string, string> = {
    orders: 'fa-file-text-o',
    shipmentRecords: 'fa-list-alt',
    products: 'fa-cubes',
    materials: 'fa-flask',
    customers: 'fa-address-book-o'
  }
  return iconMap[String(scopeKey || '')] || 'fa-file-text-o'
}

export function buildScopeTabs(): Array<{ key: string; label: string }> {
  return [
    { key: 'all', label: '全部' },
    ...Object.entries(TEMPLATE_SCOPE_CONFIG).map(([scopeKey, meta]) => ({
      key: scopeKey,
      label: meta?.label || scopeKey
    }))
  ]
}

export function buildScopeOptions(): Array<{ value: string; label: string }> {
  const options = Object.entries(TEMPLATE_SCOPE_CONFIG).map(([value, meta]) => ({
    value,
    label: value === 'custom' ? '自定义（不限业务）' : meta.label
  }))
  // 保证「自定义」始终在末尾可选（即便 JSON 未含 custom）
  if (!options.some((item) => item.value === 'custom')) {
    options.push({ value: 'custom', label: '自定义（不限业务）' })
  }
  return options
}

export function getEquivalentNormalizedTerms(term: unknown): string[] {
  const key = String(term || '').trim()
  const aliases = TERM_EQUIVALENTS[key] || [key]
  const normalized = aliases
    .map(item => normalizeTerm(item))
    .filter(Boolean)
  const targetNormalized = normalizeTerm(key)
  if (targetNormalized && !normalized.includes(targetNormalized)) {
    normalized.push(targetNormalized)
  }
  return normalized
}

export function hasEquivalentTerm(termSet: Set<string>, requiredTerm: string): boolean {
  if (!(termSet instanceof Set)) return false
  const candidates = getEquivalentNormalizedTerms(requiredTerm)
  return candidates.some(candidate => termSet.has(candidate))
}
