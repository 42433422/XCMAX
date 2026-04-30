/**
 * 核心侧栏菜单键的展示名：与 Sidebar 一致。
 * 优先级：Mod manifest `menu_overrides[].label` → 行业名 → 默认名。
 */

export type MenuOverrideRow = {
  key?: string
  label?: string
  icon?: string
  iconClass?: string
  hidden?: boolean
}

export type ModForNavLabel = {
  menu_overrides?: MenuOverrideRow[]
}

/** 与 MainLayout.viewTitlesBase 对齐，并含侧栏独有项 */
export const MENU_DEFAULT_NAMES: Record<string, string> = {
  chat: '智能对话',
  'ai-ecosystem': 'AI生态',
  brain: 'AI智脑集成',
  'model-payment': '模型支付',
  'kitten-finance': '小猫财务分析',
  'mod-store': '员工商店',
  products: '产品管理',
  'materials-list': '原材料列表',
  materials: '原材料仓库',
  'traditional-mode': '传统模式',
  'business-docking': '业务对接',
  orders: '订单管理',
  'orders-create': '新建订单',
  'shipment-records': '出货记录',
  customers: '客户管理',
  'wechat-contacts': '微信联系人列表',
  print: '标签打印',
  'printer-list': '打印机列表',
  'template-preview': '模板库',
  console: '模板库',
  settings: '系统设置',
  tools: '工具表',
  'approval-hub': '审批中心',
  'other-tools': '员工工作流管理',
  'workflow-visualization': '工作流可视化',
  purchase: '采购管理',
  'label-editor': '标签编辑器',
  'batch-analyze': '批量分析',
  'chat-debug': '聊天调试',
}

/**
 * 行业层名称：MainLayout.industryTitleMap 与 Sidebar.industryMenuNameMap 合并
 *（侧栏对 materials 等有单独条目）。
 */
export const INDUSTRY_MENU_LABELS: Record<string, Record<string, string>> = {
  涂料: {
    materials: '原材料仓库',
    products: '产品管理',
    'materials-list': '原材料列表',
    orders: '出货单管理',
    'shipment-records': '出货记录',
    customers: '客户管理',
    print: '标签打印',
  },
  电商: {
    materials: '商品仓库',
    products: '商品管理',
    'materials-list': '商品列表',
    orders: '订单管理',
    'shipment-records': '出货记录',
    customers: '买家管理',
    print: '面单打印',
  },
  餐饮: {
    materials: '食材仓库',
    products: '食材管理',
    'materials-list': '食材列表',
    orders: '订单管理',
    'shipment-records': '出货记录',
    customers: '供应商管理',
    print: '食材标签',
  },
  物流: {
    materials: '货物仓库',
    products: '货物管理',
    'materials-list': '货物列表',
    orders: '运单管理',
    'shipment-records': '出货记录',
    customers: '收发方管理',
    print: '运单打印',
  },
}

function modLabelOverride(menuKey: string, modsForUi: ModForNavLabel[] | null | undefined): string {
  if (!menuKey || !Array.isArray(modsForUi) || !modsForUi.length) return ''
  for (const mod of modsForUi) {
    const rows = mod?.menu_overrides
    if (!Array.isArray(rows)) continue
    for (const row of rows) {
      if (!row || typeof row !== 'object') continue
      if (row.hidden === true) continue
      const k = String(row.key || '').trim()
      if (k !== menuKey) continue
      const label = String(row.label || '').trim()
      if (label) return label
    }
  }
  return ''
}

export function resolveCoreNavLabel(
  menuKey: string,
  industryId: string,
  modsForUi: ModForNavLabel[] | null | undefined,
): string {
  const key = String(menuKey || '').trim()
  if (!key) return ''
  const fromMod = modLabelOverride(key, modsForUi)
  if (fromMod) return fromMod
  const byInd = INDUSTRY_MENU_LABELS[industryId] || INDUSTRY_MENU_LABELS['涂料']
  if (byInd[key]) return byInd[key]
  return MENU_DEFAULT_NAMES[key] || ''
}
