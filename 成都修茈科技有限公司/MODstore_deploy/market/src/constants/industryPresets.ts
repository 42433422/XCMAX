/**
 * 跨行业 UI 预设：优先 GET /api/system/industry-presets（FHD config/industry_presets.json）。
 */

import { industryPresetIds, industryPresets } from '../stores/hostConfig'

export type IndustryQuickButton = { text: string; label: string }

export type IndustryPreset = {
  id: string
  name: string
  scenario: string
  welcomeIntro: string
  welcomeBullets: string[]
  quickButtons: IndustryQuickButton[]
  placeholderNormal: string
  placeholderPro: string
  menuLabels: Record<string, string>
  uiLabels: Record<string, string>
}

export const INDUSTRY_PRESET_IDS = [
  '通用',
  '涂料',
  '考勤',
  '烤禽',
  '批发',
  '电商',
  '餐饮',
  '物流',
] as const

export const INDUSTRY_PRESETS: Record<string, IndustryPreset> = {
  通用: {
    id: '通用',
    name: '通用',
    scenario: '适用于多行业本地 AI 工作台，通过 Mod 扩展具体业务。',
    welcomeIntro: '您好！我是您的智能业务助手。',
    welcomeBullets: ['查询业务数据与档案', '处理单据与记录', '对接扩展 Mod 能力', '导出与打印'],
    quickButtons: [
      { text: '帮我查一下常用数据', label: '查数据' },
      { text: '打开客户或单位列表', label: '列表' },
      { text: '今天的业务单据', label: '今日单据' },
      { text: '有哪些需要处理的事项', label: '待办' },
      { text: '测试预览', label: '测试预览' },
    ],
    placeholderNormal: '普通版：输入查询或单步操作，例如「查数据」「看列表」',
    placeholderPro: '专业版：可直接下达复合任务，例如「生成单据并导出」',
    menuLabels: {},
    uiLabels: { entity: '条目', model_label: '编号', shipment_order: '业务单', records: '业务记录' },
  },
  涂料: {
    id: '涂料',
    name: '涂料/油漆',
    scenario: '涂料、油漆、固化剂等化工批发与出货。',
    welcomeIntro: '您好！我是您的涂料行业智能助手。',
    welcomeBullets: [
      '查询产品型号与价格',
      '管理客户与购买单位',
      '生成与打印出货单、标签',
      '原材料与库存预警',
    ],
    quickButtons: [
      { text: '查一下A001的价格', label: '查产品' },
      { text: '有哪些客户？', label: '客户列表' },
      { text: '今天的出货单', label: '出货单' },
      { text: '库存不足的材料', label: '库存预警' },
      { text: '帮我打印A001标签', label: '打印标签' },
      { text: '测试预览', label: '测试预览' },
    ],
    placeholderNormal: '普通版：例如「查产品」「看客户列表」「今天的出货单」',
    placeholderPro: '专业版：例如「给成都客户生成并打印今天出货单」',
    menuLabels: {
      materials: '原材料仓库',
      products: '产品管理',
      'materials-list': '原材料列表',
      orders: '出货单管理',
      'shipment-records': '出货记录',
      customers: '客户管理',
      print: '标签打印',
    },
    uiLabels: { entity: '产品', model_label: '型号', shipment_order: '出货单', records: '出货记录' },
  },
  考勤: {
    id: '考勤',
    name: '考勤/排班',
    scenario: '员工考勤、排班、请假加班与考勤表打印。',
    welcomeIntro: '您好！我是您的智能考勤助手。',
    welcomeBullets: [
      '查询员工档案与排班',
      '登记出勤、请假与加班',
      '生成与导出考勤记录',
      '打印考勤表与统计报表',
    ],
    quickButtons: [
      { text: '查询工号1001的员工信息', label: '查员工' },
      { text: '研发部今天谁出勤', label: '今日出勤' },
      { text: '生成本月考勤单', label: '考勤单' },
      { text: '登记李四请假半天', label: '请假登记' },
      { text: '打印考勤表', label: '打印考勤' },
      { text: '测试预览', label: '测试预览' },
    ],
    placeholderNormal: '普通版：例如「查员工」「登记出勤」「生成考勤单」',
    placeholderPro: '专业版：例如「汇总研发部本月考勤并导出」',
    menuLabels: {
      materials: '排班资源',
      products: '人员管理',
      'materials-list': '班次列表',
      orders: '考勤单管理',
      'shipment-records': '考勤记录',
      customers: '部门管理',
      print: '考勤表打印',
    },
    uiLabels: { entity: '员工', model_label: '工号', shipment_order: '考勤单', records: '考勤记录' },
  },
  烤禽: {
    id: '烤禽',
    name: '烤禽/熟食',
    scenario: '烤禽加工、冷链出货、门店与批发配送。',
    welcomeIntro: '您好！我是您的烤禽业务智能助手。',
    welcomeBullets: [
      '查询货品规格与报价',
      '管理门店与客户要货',
      '生成配送单与出货记录',
      '批次与库存、标签打印',
    ],
    quickButtons: [
      { text: '查一下今日烤鸡批发价', label: '查货品' },
      { text: '有哪些门店客户', label: '客户列表' },
      { text: '今天的配送单', label: '配送单' },
      { text: '哪些货品库存偏低', label: '库存预警' },
      { text: '打印货品标签', label: '打印标签' },
      { text: '测试预览', label: '测试预览' },
    ],
    placeholderNormal: '普通版：例如「查货品」「门店列表」「今天配送单」',
    placeholderPro: '专业版：例如「汇总今日门店要货并生成配送单」',
    menuLabels: {
      materials: '原料/半成品',
      products: '货品管理',
      'materials-list': '原料清单',
      orders: '配送/出货单',
      'shipment-records': '出货记录',
      customers: '门店/客户',
      print: '货品标签',
    },
    uiLabels: { entity: '货品', model_label: '货号', shipment_order: '配送单', records: '出货记录' },
  },
  批发: {
    id: '批发',
    name: '批发/分销',
    scenario: '多 SKU 批发、客户分级报价与批量开单。',
    welcomeIntro: '您好！我是您的批发业务智能助手。',
    welcomeBullets: ['查产品与批发价', '客户要货与账期', '批量开单与出货', '库存与对账导出'],
    quickButtons: [
      { text: '查一下畅销品库存', label: '查库存' },
      { text: '批发客户列表', label: '客户' },
      { text: '今天的批发单', label: '批发单' },
      { text: '低于安全库存的SKU', label: '库存预警' },
      { text: '测试预览', label: '测试预览' },
    ],
    placeholderNormal: '普通版：例如「查批发价」「客户列表」「今日批发单」',
    placeholderPro: '专业版：例如「按区域客户批量生成出货单」',
    menuLabels: {
      products: '商品管理',
      orders: '批发单',
      'shipment-records': '出货记录',
      customers: '客户管理',
      print: '单据打印',
    },
    uiLabels: { entity: '商品', shipment_order: '批发单' },
  },
  电商: {
    id: '电商',
    name: '电商/零售',
    scenario: '商品、订单与面单发货。',
    welcomeIntro: '您好！我是您的电商运营助手。',
    welcomeBullets: ['查 SKU 与库存', '订单与售后', '面单与发货', '买家与客服话术'],
    quickButtons: [
      { text: '查 SKU 10001 库存', label: '查商品' },
      { text: '今日待发货订单', label: '待发货' },
      { text: '测试预览', label: '测试预览' },
    ],
    placeholderNormal: '普通版：例如「查商品」「今日订单」',
    placeholderPro: '专业版：例如「汇总待发货订单并导出」',
    menuLabels: {
      products: '商品管理',
      orders: '订单管理',
      'shipment-records': '出货记录',
      customers: '买家管理',
      print: '面单打印',
    },
    uiLabels: { entity: '商品', shipment_order: '订单' },
  },
  餐饮: {
    id: '餐饮',
    name: '餐饮',
    scenario: '食材、门店订货与厨房领用。',
    welcomeIntro: '您好！我是您的餐饮门店助手。',
    welcomeBullets: ['食材与菜品', '门店订货', '供应商对账', '标签与打印'],
    quickButtons: [
      { text: '查今日食材库存', label: '查食材' },
      { text: '门店订货列表', label: '订货' },
      { text: '测试预览', label: '测试预览' },
    ],
    placeholderNormal: '普通版：例如「查食材」「门店订货」',
    placeholderPro: '专业版：例如「汇总各门店要货单」',
    menuLabels: {
      materials: '食材仓库',
      products: '菜品/食材',
      orders: '订货单',
      customers: '供应商',
      print: '食材标签',
    },
    uiLabels: { entity: '食材', shipment_order: '订货单' },
  },
  物流: {
    id: '物流',
    name: '物流',
    scenario: '运单、收发方与在途跟踪。',
    welcomeIntro: '您好！我是您的物流调度助手。',
    welcomeBullets: ['运单查询', '收发方管理', '在途与签收', '运单打印'],
    quickButtons: [
      { text: '查在途运单', label: '在途' },
      { text: '今日新建运单', label: '运单' },
      { text: '测试预览', label: '测试预览' },
    ],
    placeholderNormal: '普通版：例如「查运单」「今日发运」',
    placeholderPro: '专业版：例如「批量生成运单并打印」',
    menuLabels: {
      products: '货物管理',
      orders: '运单管理',
      customers: '收发方',
      print: '运单打印',
    },
    uiLabels: { entity: '货物', shipment_order: '运单' },
  },
}

export function listIndustryPresetIdList(): string[] {
  const apiIds = industryPresetIds.value
  if (apiIds.length > 0) return [...apiIds]
  return [...INDUSTRY_PRESET_IDS]
}

export function getIndustryPreset(industryId: string): IndustryPreset {
  const id = String(industryId || '').trim() || '通用'
  const apiMap = industryPresets.value
  if (apiMap[id]) return apiMap[id]
  return INDUSTRY_PRESETS[id] || INDUSTRY_PRESETS['通用']
}

export function listIndustryPresets(): IndustryPreset[] {
  return listIndustryPresetIdList().map((id) => getIndustryPreset(id))
}

export function getIndustryQuickButtons(industryId: string): IndustryQuickButton[] {
  return [...getIndustryPreset(industryId).quickButtons]
}

export function getIndustryWelcomeMarkdown(industryId: string): string {
  const p = getIndustryPreset(industryId)
  const bullets = p.welcomeBullets.map((b) => `- ${b}`).join('\n')
  return `${p.welcomeIntro}\n\n我可以帮您：\n\n${bullets}\n\n请直接说出您的需求`
}

export function manifestIndustryFromPreset(presetId: string): Record<string, unknown> {
  const p = getIndustryPreset(presetId)
  return {
    id: p.id,
    name: p.name,
    scenario: p.scenario,
    description: p.scenario,
    units: { primary: '件', primary_label: '数量' },
    product_fields: {
      name: p.uiLabels.entity || '名称',
      model: p.uiLabels.model_label || '编号',
    },
    ui_labels: p.uiLabels,
    menu_overrides: Object.entries(p.menuLabels).map(([key, label]) => ({ key, label })),
  }
}
