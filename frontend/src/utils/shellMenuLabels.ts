/**
 * 宿主侧栏 / 顶栏页面标题 / 各业务页 h2 共用的「行业 + manifest.shell_menu_preset」文案解析。
 * 与 Sidebar.vue 中逻辑保持一致；请勿在 MainLayout / ProductsView 再硬编码一套 map。
 */

export type ShellModLike = {
  id: string
  shell_menu_preset?: string
  shellMenuPreset?: string
  shell_tagline?: string
  shellTagline?: string
  primary?: boolean
  /** manifest 常见写法：与 frontend.menu 同级 */
  frontend?: { shell_menu_preset?: string; shellMenuPreset?: string; shell_tagline?: string; shellTagline?: string }
}

function pickShellStr(
  mod: unknown,
  snake: 'shell_menu_preset' | 'shell_tagline' | 'library_blurb',
  camel: string
): string {
  if (!mod || typeof mod !== 'object') return ''
  const tryPair = (src: Record<string, unknown>) => {
    const a = src[snake]
    if (typeof a === 'string' && a.trim()) return a.trim()
    const b = src[camel]
    if (typeof b === 'string' && b.trim()) return b.trim()
    return ''
  }
  const m = mod as Record<string, unknown>
  const x = tryPair(m)
  if (x) return x
  const fe = m.frontend
  if (fe && typeof fe === 'object') return tryPair(fe as Record<string, unknown>)
  return ''
}

/** 从扩展条目解析 manifest 菜单预设键（兼容 camelCase 与 frontend.*） */
export function readShellMenuPreset(mod: unknown): string {
  return pickShellStr(mod, 'shell_menu_preset', 'shellMenuPreset')
}

export function readShellTagline(mod: unknown): string {
  return pickShellStr(mod, 'shell_tagline', 'shellTagline')
}

/** 与 MainLayout 原 viewTitlesBase 一致（全路由标题默认值） */
export const SHELL_VIEW_TITLE_BASE: Record<string, string> = {
  chat: '智能对话',
  'ai-ecosystem': 'AI生态',
  brain: 'AI智脑集成',
  'model-payment': '模型支付',
  products: '产品管理',
  'materials-list': '原材料列表',
  materials: '原材料仓库',
  'traditional-mode': '传统模式',
  'business-docking': '业务对接',
  orders: '订单管理',
  'orders-create': '新建订单',
  purchase: '采购管理',
  'shipment-records': '出货记录',
  customers: '客户管理',
  'wechat-contacts': '微信联系人列表',
  print: '标签打印',
  'printer-list': '打印机列表',
  'template-preview': '模板库',
  'label-editor': '标签编辑器',
  console: '模板库',
  settings: '系统设置',
  tools: '工具表',
  'other-tools': '员工工作流管理',
  'approval-hub': '审批中心',
  'approval-workspace': '审批工作台',
  'approval-flow-management': '审批流程管理',
  'approval-rules': '审批流程规则',
  'workflow-visualization': '工作流可视化',
  'workflow-employee-space': '员工空间',
  'workflow-employee-stitch-full': '员工工作流全景',
  'batch-analyze': '批量分析',
  'kitten-finance': '🐱 小猫财务分析',
  'chat-debug': '聊天调试',
  'mod-store': '员工商店'
}

/**
 * 按「当前行业」与 manifest.shell_menu_preset 覆盖的菜单/标题片段。
 * 键为路由侧栏 key（与 route.name / Sidebar menu key 一致）。
 */
export const SHELL_INDUSTRY_MENU_OVERRIDES: Record<string, Record<string, string>> = {
  通用: {},
  涂料: {
    products: '产品管理',
    materials: '原材料仓库',
    'materials-list': '原材料列表',
    'shipment-records': '出货记录',
    customers: '客户管理',
    print: '标签打印'
  },
  电商: {
    products: '商品管理',
    materials: '商品仓库',
    'materials-list': '商品列表',
    'shipment-records': '出货记录',
    customers: '买家管理',
    print: '面单打印'
  },
  餐饮: {
    products: '食材管理',
    materials: '食材仓库',
    'materials-list': '食材列表',
    'shipment-records': '出货记录',
    customers: '供应商管理',
    print: '食材标签'
  },
  物流: {
    products: '货物管理',
    materials: '货物仓库',
    'materials-list': '货物列表',
    'shipment-records': '出货记录',
    customers: '收发方管理',
    print: '运单打印'
  },
  员工管理: {
    products: '员工与档案',
    materials: '制度与资料库',
    'materials-list': '资料目录',
    'shipment-records': '考勤与排班',
    customers: '协作关系',
    print: '标签打印',
    'business-docking': '人事对接',
    'other-tools': '员工工作流',
    'approval-rules': '审批流程规则'
  }
}

export function getActiveShellMod(modList: ShellModLike[], activeExtensionModId: string): ShellModLike | null {
  const list = modList || []
  const pick = String(activeExtensionModId || '').trim()
  if (pick) {
    const hit = list.find((m) => m.id === pick)
    if (hit) return hit
  }
  const prim = list.find((m) => m.primary)
  return prim || list[0] || null
}

/** 与 Sidebar effectiveMenuIndustryId 一致 */
export function effectiveShellMenuIndustryId(
  currentIndustryId: string,
  modList: ShellModLike[],
  activeExtensionModId: string
): string {
  const mod = getActiveShellMod(modList, activeExtensionModId)
  const preset = readShellMenuPreset(mod)
  if (preset && SHELL_INDUSTRY_MENU_OVERRIDES[preset]) return preset
  return String(currentIndustryId || '涂料')
}

/** 合并后的顶栏/页面标题表（先默认表，再叠行业与 shell_menu_preset） */
export function mergeShellViewTitles(
  currentIndustryId: string,
  modList: ShellModLike[],
  activeExtensionModId: string
): Record<string, string> {
  const ind = effectiveShellMenuIndustryId(currentIndustryId, modList, activeExtensionModId)
  const layer = SHELL_INDUSTRY_MENU_OVERRIDES[ind] || SHELL_INDUSTRY_MENU_OVERRIDES['涂料'] || {}
  return { ...SHELL_VIEW_TITLE_BASE, ...layer }
}
