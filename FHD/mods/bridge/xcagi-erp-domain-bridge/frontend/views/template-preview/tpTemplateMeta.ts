import {
  TEMPLATE_SCOPE_CONFIG,
  getScopeMeta,
  getRequiredTermsByScope,
  hasEquivalentTerm,
  isKnownScopeKey,
  normalizeTerm,
} from './tpScopeRules'

/** 模板字段（与后端模板 fields 结构对应的宽松契约） */
export interface TplField {
  id?: number | string
  label?: string
  name?: string
  value?: string
  type?: string
  position?: { left?: number; top?: number; width?: number; height?: number }
}

/** Excel 网格预览结构（rows 为二维单元格，单元格可为文本或带样式对象） */
export interface GridPreview {
  rows?: unknown[]
  [key: string]: unknown
}

/** 模板 preview_data 宽松契约（后端历史字段较杂，未列举键以 unknown 兜底） */
export interface TplPreviewData {
  sample_rows?: Record<string, unknown>[]
  sheet_name?: string
  selected_sheet_name?: string
  sheet_names?: string[]
  grid_preview?: GridPreview | null
  cells?: Record<string, { value?: unknown } | undefined>
  placeholders?: unknown[]
  custom_scope_label?: string
  file_path?: string
  original_filename?: string
  [key: string]: unknown
}

/** 模板词条覆盖率结果 */
export interface TemplateCoverage {
  scope: string
  requiredCount: number
  missing: string[]
  matchedCount: number
}

/** 与原视图一致的松散模板记录类型（原为无类型 JS 对象） */
export interface TplRecord {
  id: string
  name?: string
  category?: string
  template_type?: string
  business_scope?: string
  source?: string
  virtual?: boolean
  filename?: string
  file_path?: string
  path?: string
  fields?: TplField[]
  preview_data?: TplPreviewData | null
  is_active?: number | boolean
  [key: string]: unknown
}

const EXPORT_TEMPLATE_SOURCES = new Set([
  'db',
  'generated',
  'business-docking',
  'template-preview-replace',
  'system-default',
  'fs_scan'
])

export function isExportTemplate(tpl: TplRecord | null): boolean {
  if (!tpl || tpl.virtual) return false
  if (tpl.category !== 'excel' && tpl.category !== 'word') return false
  const source = String(tpl.source || '').trim()
  if (EXPORT_TEMPLATE_SOURCES.has(source)) return true
  if (String(tpl.id || '').startsWith('db:')) return true
  return false
}

export function getTemplateSourceLabel(tpl: TplRecord | null): string {
  const source = String(tpl?.source || 'db').trim()
  const sourceLabelMap: Record<string, string> = {
    db: '数据库',
    generated: '生成',
    'business-docking': '业务对接',
    'template-preview-replace': '模板替代',
    'system-default': '系统默认',
    fs_scan: '本地扫描（项目目录）'
  }
  return sourceLabelMap[source] || source
}

export function getTemplateFields(tpl: TplRecord | null, type: string): TplField[] {
  if (tpl?.fields && tpl.fields.length > 0) {
    return tpl.fields
  }

  if (type === 'label') {
    return [
      { label: '品名', value: 'XX运动鞋', type: 'fixed' },
      { label: '货号', value: '1635', type: 'dynamic' },
      { label: '颜色', value: '白色', type: 'dynamic' },
      { label: '码段', value: '00001', type: 'dynamic' },
      { label: '等级', value: '合格品', type: 'fixed' },
      { label: '统一零售价', value: '¥199', type: 'dynamic' }
    ]
  }

  return [
    { label: '产品型号', value: '' },
    { label: '产品名称', value: '' },
    { label: '数量', value: '' },
    { label: '单价', value: '' },
    { label: '金额', value: '' }
  ]
}

export function getTemplateSampleRows(tpl: TplRecord | null): Record<string, unknown>[] {
  if (tpl?.preview_data && tpl.preview_data.sample_rows) {
    return tpl.preview_data.sample_rows
  }
  return []
}

export function getTemplateGridData(tpl: TplRecord | null): GridPreview | undefined {
  return tpl?.preview_data?.grid_preview || undefined
}

export function getExcelPreviewTitle(tpl: TplRecord | null): string {
  if (!tpl) return 'Excel 模板预览'
  const text = tpl.template_type || tpl.name || 'Excel 模板'
  return `${text}预览`
}

export function canDeleteTemplate(tpl: TplRecord | null): boolean {
  if (!tpl || tpl.virtual) return false
  const id = String(tpl.id || '').trim()
  return id.startsWith('db:') || id.startsWith('fs:')
}

export function canPreviewVirtualTemplate(tpl: TplRecord | null): boolean {
  if (!tpl || tpl.category !== 'excel') return false
  const fields = getTemplateFields(tpl, 'excel')
  const sampleRows = getTemplateSampleRows(tpl)
  const gridData = getTemplateGridData(tpl)
  return (Array.isArray(fields) && fields.length > 0) && (
    (Array.isArray(sampleRows) && sampleRows.length > 0) ||
    (gridData != null && Array.isArray(gridData.rows) && gridData.rows.length > 0)
  )
}

export function createVirtualTemplate(scopeKey: string): TplRecord {
  const meta = getScopeMeta(scopeKey) || { label: '业务模板', templateType: '发货单', requiredTerms: [] }
  const requiredTerms = Array.isArray(meta.requiredTerms) ? meta.requiredTerms : []
  // 未上传真实模板时只保留"必备词条骨架"，不再塞入 sample_rows/grid_preview 这些假样例数据，
  // 这样 `canPreviewVirtualTemplate` 会判为 false，前端会展示"待上传 Excel 模板 + 必备词条"的占位卡片，
  // 而不是误导性的 M001/示例产品 预览网格。
  return {
    id: `virtual:${scopeKey}`,
    name: `${meta.label}模板`,
    category: 'excel',
    template_type: meta.templateType,
    business_scope: scopeKey,
    source: 'virtual',
    virtual: true,
    fields: requiredTerms.map(term => ({ label: term, value: '', type: 'dynamic' })),
    preview_data: {
      sample_rows: [],
      sheet_name: String(meta.templateType || '导出模板'),
      grid_preview: null
    }
  }
}

export function inferWordTemplateScopeKey(tpl: TplRecord | null): string {
  const id = String(tpl?.id || '').toLowerCase()
  const name = String(tpl?.name || '').toLowerCase()
  const fn = String(tpl?.filename || '').toLowerCase()
  const blob = `${id} ${name} ${fn}`
  if (/price_list|pricelist|价目|价格表|产品目录/.test(blob)) return 'products'
  if (/sales_cn|contract|合同|报价/.test(blob)) return 'orders'
  if (/出货记录|shipment.?record|delivery.?record/.test(blob)) return 'shipmentRecords'
  if (/customer|客户名录|客户管理/.test(blob)) return 'customers'
  if (/material|原材料|库存/.test(blob)) return 'materials'
  if (/summary|汇总统计|合计汇总/.test(blob)) return 'shipmentSummary'
  if (/sales.?report|销售报表|营收/.test(blob)) return 'salesReport'
  return ''
}

export function getTemplateScopeKey(tpl: TplRecord | null): string {
  if (tpl?.category === 'word') {
    const explicitScope = String(tpl?.business_scope || '').trim()
    if (isKnownScopeKey(explicitScope)) {
      return explicitScope
    }
    const inferred = inferWordTemplateScopeKey(tpl)
    if (isKnownScopeKey(inferred)) {
      return inferred
    }
    return ''
  }
  const explicitScope = String(tpl?.business_scope || '').trim()
  if (isKnownScopeKey(explicitScope)) {
    return explicitScope
  }
  const matched = getMatchedScopeKeys(tpl)
  return matched[0] || ''
}

export function getTemplateScopeLabel(tpl: TplRecord | null): string {
  const scopeKey = getTemplateScopeKey(tpl)
  if (scopeKey === 'custom') {
    const customLabel = String(tpl?.preview_data?.custom_scope_label || '').trim()
    if (customLabel) return customLabel
    return getScopeMeta('custom')?.label || '自定义'
  }
  const meta = getScopeMeta(scopeKey)
  return (meta?.label || scopeKey || '未分类')
}

export function extractTemplateTermSet(
  fields?: TplField[] | null,
  previewData?: TplPreviewData | null
): Set<string> {
  const terms = new Set<string>()
  for (const field of fields || []) {
    terms.add(normalizeTerm(field?.label))
    terms.add(normalizeTerm(field?.name))
    terms.add(normalizeTerm(field?.value))
  }
  const cells = previewData?.cells || {}
  for (const key of Object.keys(cells)) {
    const cellValue = cells[key]?.value
    terms.add(normalizeTerm(cellValue))
  }
  const sampleRows = Array.isArray(previewData?.sample_rows) ? previewData.sample_rows : []
  for (const row of sampleRows) {
    for (const key of Object.keys(row || {})) {
      terms.add(normalizeTerm(key))
      terms.add(normalizeTerm(row?.[key]))
    }
  }
  const ph = previewData?.placeholders
  if (Array.isArray(ph)) {
    for (const item of ph) {
      terms.add(normalizeTerm(item))
    }
  }
  return terms
}

export function extractTemplateDisplayTerms(
  fields?: TplField[] | null,
  previewData?: TplPreviewData | null
): string[] {
  const displayTerms: string[] = []
  const pushTerm = (v: unknown) => {
    const text = String(v || '').trim()
    if (!text) return
    if (!displayTerms.includes(text)) {
      displayTerms.push(text)
    }
  }
  for (const field of fields || []) {
    pushTerm(field?.label)
    pushTerm(field?.name)
  }
  const cells = previewData?.cells || {}
  for (const key of Object.keys(cells)) {
    pushTerm(cells[key]?.value)
  }
  const sampleRows = Array.isArray(previewData?.sample_rows) ? previewData.sample_rows : []
  for (const row of sampleRows) {
    for (const key of Object.keys(row || {})) {
      pushTerm(key)
    }
  }
  const ph = previewData?.placeholders
  if (Array.isArray(ph)) {
    for (const item of ph) {
      pushTerm(item)
    }
  }
  return displayTerms
}

export function getTemplateDisplayTermsText(tpl: TplRecord | null): string {
  const terms = extractTemplateDisplayTerms(tpl?.fields, tpl?.preview_data)
  if (!terms.length) return '无'
  const maxShow = 8
  if (terms.length <= maxShow) return terms.join('、')
  return `${terms.slice(0, maxShow).join('、')} 等 ${terms.length} 项`
}

export function getTemplateTypeLabel(tpl: TplRecord | null): string {
  if (tpl?.category === 'word') {
    const scopeKey = getTemplateScopeKey(tpl)
    const meta = getScopeMeta(scopeKey)
    const suffix = meta?.label || scopeKey || '业务'
    const tt = String(tpl?.template_type || '').trim()
    if (tt && tt.toLowerCase() !== 'excel') {
      return `Word · ${tt}`
    }
    return `Word · ${suffix}`
  }
  const originalType = String(tpl?.template_type || '').trim()
  if (originalType && originalType.toLowerCase() !== 'excel') {
    return originalType
  }

  const matchedScopeKeys = getMatchedScopeKeys(tpl)
  if (!matchedScopeKeys.length) {
    return originalType || 'Excel'
  }

  const scopeMeta = getScopeMeta(matchedScopeKeys[0])
  return scopeMeta?.templateType || scopeMeta?.label || originalType || 'Excel'
}

export function getMatchedScopeKeys(tpl: TplRecord | null): string[] {
  if (tpl?.virtual) return []
  const explicitScope = String(tpl?.business_scope || '').trim()
  if (isKnownScopeKey(explicitScope)) {
    return [explicitScope]
  }
  if (tpl?.category !== 'excel' && tpl?.category !== 'word') return []
  const termSet = extractTemplateTermSet(tpl?.fields, tpl?.preview_data)
  const matched: string[] = []
  for (const scopeKey of Object.keys(TEMPLATE_SCOPE_CONFIG)) {
    if (scopeKey === 'custom') continue
    const required = getRequiredTermsByScope(scopeKey)
    if (required.length && required.every(term => hasEquivalentTerm(termSet, term))) {
      matched.push(scopeKey)
    }
  }
  return matched
}

export function getMatchedScopeLabels(tpl: TplRecord | null): string[] {
  return getMatchedScopeKeys(tpl)
    .map(scopeKey => getScopeMeta(scopeKey)?.label)
    .filter((label): label is string => Boolean(label))
}

export function getTemplateCoverage(tpl: TplRecord | null): TemplateCoverage | null {
  if (tpl?.category !== 'excel' && tpl?.category !== 'word') return null
  const matchedScopeKeys = getMatchedScopeKeys(tpl)
  if (!matchedScopeKeys.length) return null
  const scope = matchedScopeKeys[0]
  const required = getRequiredTermsByScope(scope)
  const termSet = extractTemplateTermSet(tpl?.fields, tpl?.preview_data)
  const missing = required.filter(term => !hasEquivalentTerm(termSet, term))
  return {
    scope,
    requiredCount: required.length,
    missing,
    matchedCount: required.length - missing.length
  }
}
