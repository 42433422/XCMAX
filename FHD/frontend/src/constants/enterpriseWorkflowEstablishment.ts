/**
 * 企业端工作流「四部门」— 工具层 / 执行层 / 服务层 / 管理层。
 * 与管理端内部六部门（O-A 获客 / P-S 软件等）不同；员工从 AI 市场安装后可自动上岗至对应栏位。
 */

export type EnterpriseOrgLayerId = 'tools' | 'execution' | 'service' | 'management'

/** @deprecated 沿用旧名，与 EnterpriseOrgLayerId 相同 */
export type EnterpriseEstablishmentZoneId = EnterpriseOrgLayerId

export type EnterpriseOrgLayer = {
  id: EnterpriseOrgLayerId
  /** 企业端编制代号 L1–L4 */
  code: string
  label: string
  desc: string
  color: string
}

export type EmployeeListing = 'listed' | 'unlisted'
export type EnterpriseEmployeeMeta = {
  id: string
  label: string
  enterprise_layer: EnterpriseOrgLayerId
  listing: EmployeeListing
  source: string
  mod_id: string
}

// CI SSOT BEGIN
/** 企业端四层 + 员工层归属/上架状态（来自 config/duty_roster.json，勿手改）。 */
export const ENTERPRISE_ORG_LAYERS: readonly EnterpriseOrgLayer[] = [
  { id: 'tools', code: 'L1', label: '工具层', desc: '连接、授权、技能与通用工具 Mod', color: '#4f46e5' },
  { id: 'execution', code: 'L2', label: '执行层', desc: '出货、打单、单据与履约执行', color: '#d97706' },
  { id: 'service', code: 'L3', label: '服务层', desc: '微信触达、客服沟通与人事服务', color: '#059669' },
  { id: 'management', code: 'L4', label: '管理层', desc: '流程编排、路由协同与自治监控', color: '#7c3aed' },
] as const
export const ENTERPRISE_EMPLOYEES: Record<string, EnterpriseEmployeeMeta> = {
  'wechat_contacts': { id: 'wechat_contacts', label: '企微联系人', enterprise_layer: 'service', listing: 'listed', source: 'store', mod_id: 'wechat-contacts-ai-employee' },
  'lan_gate': { id: 'lan_gate', label: '局域网网关', enterprise_layer: 'tools', listing: 'listed', source: 'store', mod_id: 'lan-gate-ai-employee' },
  'label_print': { id: 'label_print', label: '标签打印', enterprise_layer: 'execution', listing: 'unlisted', source: 'custom', mod_id: 'xcagi-core-workflow-employees' },
  'shipment_mgmt': { id: 'shipment_mgmt', label: '出货管理', enterprise_layer: 'execution', listing: 'unlisted', source: 'custom', mod_id: 'xcagi-core-workflow-employees' },
  'receipt_confirm': { id: 'receipt_confirm', label: '签收确认', enterprise_layer: 'execution', listing: 'unlisted', source: 'custom', mod_id: 'xcagi-core-workflow-employees' },
  'wechat_msg': { id: 'wechat_msg', label: '微信消息', enterprise_layer: 'service', listing: 'unlisted', source: 'custom', mod_id: 'xcagi-core-workflow-employees' },
  'workflow_automator': { id: 'workflow_automator', label: '流程自动化', enterprise_layer: 'management', listing: 'unlisted', source: 'custom', mod_id: 'xcagi-core-workflow-employees' },
  'task_router_officer': { id: 'task_router_officer', label: '任务派发', enterprise_layer: 'management', listing: 'unlisted', source: 'custom', mod_id: 'xcagi-core-workflow-employees' },
  'daily_orchestrator': { id: 'daily_orchestrator', label: '每日编排', enterprise_layer: 'management', listing: 'unlisted', source: 'custom', mod_id: 'xcagi-core-workflow-employees' },
  'excel_generate': { id: 'excel_generate', label: 'Excel 生成', enterprise_layer: 'execution', listing: 'unlisted', source: 'custom', mod_id: 'xcagi-office-employee-pack-bridge' },
  'word_generate': { id: 'word_generate', label: 'Word 生成', enterprise_layer: 'execution', listing: 'unlisted', source: 'custom', mod_id: 'xcagi-office-employee-pack-bridge' },
  'ppt_generate': { id: 'ppt_generate', label: 'PPT 生成', enterprise_layer: 'execution', listing: 'unlisted', source: 'custom', mod_id: 'xcagi-office-employee-pack-bridge' },
  'pdf_generate': { id: 'pdf_generate', label: 'PDF 生成', enterprise_layer: 'execution', listing: 'unlisted', source: 'custom', mod_id: 'xcagi-office-employee-pack-bridge' },
}
// CI SSOT END

/** @deprecated 与 ENTERPRISE_ORG_LAYERS 相同 */
export const ENTERPRISE_ESTABLISHMENT_ZONES = ENTERPRISE_ORG_LAYERS

export type EnterpriseEstablishmentZone = EnterpriseOrgLayer

const LAYER_ID_SET = new Set<string>(ENTERPRISE_ORG_LAYERS.map((z) => z.id))

const MANIFEST_LAYER_ALIASES: Record<string, EnterpriseOrgLayerId> = {
  tools: 'tools',
  tool: 'tools',
  tool_layer: 'tools',
  工具层: 'tools',
  工具: 'tools',
  execution: 'execution',
  action: 'execution',
  execution_layer: 'execution',
  执行层: 'execution',
  执行: 'execution',
  service: 'service',
  collaboration: 'service',
  service_layer: 'service',
  服务层: 'service',
  服务: 'service',
  management: 'management',
  manage: 'management',
  management_layer: 'management',
  管理层: 'management',
  管理: 'management',
}

/**
 * 客户行业包 / 别名变体员工的层兜底（不在 SSOT ENTERPRISE_EMPLOYEES 内）。
 * 中央平台员工的层归属一律走 SSOT（resolveEnterpriseOrgLayer 已优先查 ENTERPRISE_EMPLOYEES）；
 * 这里只保留 SSOT 未收录的客户专属/历史别名，禁止与 SSOT 重叠（见 test_employee_ssot 守卫）。
 */
const EMP_ID_LAYER: Record<string, EnterpriseOrgLayerId> = {
  wechat_contacts_hub: 'service', // wechat-contacts-ai-employee 变体
  wechat_phone: 'service', // sz-qsm-pro 客户包
  lan_gate_hub: 'tools', // lan-gate-ai-employee 变体
  lan_gate_ai: 'tools', // 历史别名
  attendance_ai: 'service', // taiyangniao-pro 客户包
  coating_ai: 'service', // sz-qsm-pro 客户包
  taiyangniao_attendance: 'service', // 历史别名
}

function normalizeBlob(empId: string, shortName?: string, panelTitle?: string): string {
  return `${empId} ${shortName || ''} ${panelTitle || ''}`.toLowerCase().replace(/[_-]+/g, ' ')
}

export function normalizeEnterpriseOrgLayerId(raw: string | undefined | null): EnterpriseOrgLayerId | null {
  const key = String(raw || '').trim().toLowerCase()
  if (!key) return null
  if (LAYER_ID_SET.has(key)) return key as EnterpriseOrgLayerId
  return MANIFEST_LAYER_ALIASES[key] ?? MANIFEST_LAYER_ALIASES[String(raw || '').trim()] ?? null
}

/**
 * 将工作流员工归入企业四部门之一；manifest 显式 enterprise_layer 优先。
 */
export function resolveEnterpriseOrgLayer(
  empId: string,
  shortName?: string,
  panelTitle?: string,
  manifestLayer?: string,
): EnterpriseOrgLayerId {
  const fromManifest = normalizeEnterpriseOrgLayerId(manifestLayer)
  if (fromManifest) return fromManifest

  // SSOT 优先：config/duty_roster.json enterprise_employees（查表，非猜测）
  const rawId = String(empId || '').trim()
  const ssot = ENTERPRISE_EMPLOYEES[rawId] || ENTERPRISE_EMPLOYEES[rawId.toLowerCase()]
  if (ssot) return ssot.enterprise_layer

  const id = rawId.toLowerCase()
  if (id && EMP_ID_LAYER[id]) return EMP_ID_LAYER[id]

  const blob = normalizeBlob(empId, shortName, panelTitle)
  if (/局域网|lan|授权|接入|gate|token|连接|工具|tool|skill|ocr|adapter/.test(blob)) return 'tools'
  if (/出货|收货|发货|shipment|receipt|delivery|履约|订单|对账|标签|打印|label|print|单据|票据|条码|excel|word|pdf|ppt|csv/.test(blob)) {
    return 'execution'
  }
  if (/微信|wechat|消息|触点|客服|沟通|contacts|考勤|attendance|人事|排班|出勤|taiyangniao|太阳鸟/.test(blob)) {
    return 'service'
  }
  if (/编排|路由|orchestr|router|监控|自治|管理|workflow_auto|automator|dispatcher/.test(blob)) {
    return 'management'
  }
  return 'management'
}

/** @deprecated 使用 resolveEnterpriseOrgLayer */
export function resolveEnterpriseEstablishmentZone(
  empId: string,
  shortName?: string,
  panelTitle?: string,
): EnterpriseOrgLayerId {
  return resolveEnterpriseOrgLayer(empId, shortName, panelTitle)
}

export function countEnterpriseEstablishmentMaxSlots(
  desks: { empId: string; shortName?: string; panelTitle?: string }[],
): number {
  const counts = new Map<EnterpriseOrgLayerId, number>()
  for (const z of ENTERPRISE_ORG_LAYERS) counts.set(z.id, 0)
  for (const row of desks) {
    const zid = resolveEnterpriseOrgLayer(row.empId, row.shortName, row.panelTitle)
    counts.set(zid, (counts.get(zid) ?? 0) + 1)
  }
  const max = Math.max(0, ...counts.values())
  return Math.max(1, max)
}

export function enterpriseOrgLayerById(id: string): EnterpriseOrgLayer | undefined {
  if (!LAYER_ID_SET.has(id)) return undefined
  return ENTERPRISE_ORG_LAYERS.find((z) => z.id === id)
}

/** @deprecated 使用 enterpriseOrgLayerById */
export function enterpriseEstablishmentZoneById(id: string): EnterpriseOrgLayer | undefined {
  return enterpriseOrgLayerById(id)
}

export type EnterpriseOrgLayerCatalogInput = {
  id?: string
  pkg_id?: string
  name?: string
  description?: string
  artifact?: string
  store_collection?: string
  employee?: { id?: string; label?: string }
  workflow_employees?: Array<{ id?: string; label?: string; enterprise_layer?: string }>
  enterprise_layer?: string
}

/** AI 市场商品卡：推断所属四部门（用于色标/标签） */
export function resolveEnterpriseOrgLayerForCatalogItem(
  row: EnterpriseOrgLayerCatalogInput,
): EnterpriseOrgLayer | undefined {
  const top = normalizeEnterpriseOrgLayerId(row.enterprise_layer)
  if (top) return enterpriseOrgLayerById(top)

  const wf = row.workflow_employees
  if (Array.isArray(wf) && wf.length) {
    for (const e of wf) {
      const layer = normalizeEnterpriseOrgLayerId(e.enterprise_layer)
      if (layer) return enterpriseOrgLayerById(layer)
      const inferred = resolveEnterpriseOrgLayer(
        String(e.id || ''),
        String(e.label || ''),
        '',
        e.enterprise_layer,
      )
      return enterpriseOrgLayerById(inferred)
    }
  }

  const emp = row.employee
  if (emp && typeof emp === 'object') {
    const inferred = resolveEnterpriseOrgLayer(
      String(emp.id || row.id || row.pkg_id || ''),
      String(emp.label || row.name || ''),
      row.description,
    )
    return enterpriseOrgLayerById(inferred)
  }

  const blob = `${row.id || ''} ${row.pkg_id || ''} ${row.name || ''} ${row.description || ''}`
    .toLowerCase()
    .replace(/[_-]+/g, ' ')
  const inferred = resolveEnterpriseOrgLayer(blob, row.name, row.description)
  return enterpriseOrgLayerById(inferred)
}
