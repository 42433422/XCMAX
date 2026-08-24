import {
  ONBOARDING_INDUSTRY_CATEGORIES,
  ONBOARDING_INDUSTRY_OPTIONS,
  type OnboardingIndustryCategoryId,
} from '@/constants/onboardingIndustryCatalog'

export type IndustryBusinessMenuKey =
  | 'erp-hr'
  | 'products'
  | 'customers'
  | 'orders'
  | 'shipment-records'
  | 'materials'
  | 'inventory'
  | 'approval-hub'
  | 'data-sources'
  | 'print'
  | 'printer-list'
  | 'template-preview'
  | 'business-docking'

export type IndustrySidebarPreviewKey = IndustryBusinessMenuKey | 'persy-knowledge'

export type IndustryNavigationProfile = {
  id: string
  categoryId: OnboardingIndustryCategoryId
  categoryLabel: string
  businessMenuKeys: IndustryBusinessMenuKey[]
  previewMenuKeys: IndustrySidebarPreviewKey[]
  menuLabels: Partial<Record<IndustrySidebarPreviewKey, string>>
  /** 尚无对应真实业务页，只用于在引导中如实提示，不得生成侧栏入口。 */
  deferredCapabilities: string[]
}

function withDefaultErpFoundation<T extends IndustrySidebarPreviewKey>(
  keys: T[],
): Array<T | 'erp-hr' | 'template-preview'> {
  const out: Array<T | 'erp-hr' | 'template-preview'> = [...keys]
  if (!out.some((key) => key === 'erp-hr')) out.push('erp-hr')
  if (!out.some((key) => key === 'template-preview')) out.push('template-preview')
  return out
}

const categoryLabelById = Object.fromEntries(ONBOARDING_INDUSTRY_CATEGORIES.map((item) => [item.id, item.label])) as Record<
  OnboardingIndustryCategoryId,
  string
>

const profile = (
  categoryId: OnboardingIndustryCategoryId,
  businessMenuKeys: IndustryBusinessMenuKey[],
  previewMenuKeys: IndustrySidebarPreviewKey[],
  menuLabels: IndustryNavigationProfile['menuLabels'],
  deferredCapabilities: string[],
): IndustryNavigationProfile => ({
  id: categoryId,
  categoryId,
  categoryLabel: categoryLabelById[categoryId],
  businessMenuKeys: withDefaultErpFoundation(businessMenuKeys),
  previewMenuKeys: withDefaultErpFoundation(previewMenuKeys),
  menuLabels,
  deferredCapabilities,
})

/**
 * 九大行业只编排已存在且可落到真实页面/API 的宿主能力。
 * 项目、合同、质检、BOM 等尚无独立业务页的概念只能列入 deferredCapabilities，
 * 不能借已有订单或库存路由换名后冒充。
 */
export const INDUSTRY_NAVIGATION_PROFILES: Record<OnboardingIndustryCategoryId, IndustryNavigationProfile> = {
  manufacturing: profile(
    'manufacturing',
    ['products', 'materials', 'inventory', 'customers', 'orders', 'shipment-records', 'approval-hub', 'data-sources'],
    ['products', 'materials', 'inventory', 'orders', 'shipment-records', 'customers', 'persy-knowledge'],
    {
      products: '产品管理',
      materials: '物料管理',
      inventory: '库存管理',
      customers: '客户管理',
      orders: '销售订单',
      'shipment-records': '出货记录',
      'approval-hub': '审批工作台',
      'data-sources': '生产数据源',
    },
    ['生产工单', '质检', 'BOM'],
  ),
  commerce: profile(
    'commerce',
    ['products', 'customers', 'orders', 'inventory', 'shipment-records', 'data-sources', 'print', 'template-preview'],
    ['products', 'customers', 'orders', 'inventory', 'shipment-records', 'print', 'persy-knowledge'],
    {
      products: '商品管理',
      customers: '客户管理',
      orders: '销售订单',
      inventory: '库存管理',
      'shipment-records': '出货记录',
      'data-sources': '经营数据源',
      print: '单据打印',
      'template-preview': '单据模板',
    },
    ['门店管理', '会员体系', '采购计划'],
  ),
  construction: profile(
    'construction',
    ['products', 'customers', 'orders', 'shipment-records', 'materials', 'approval-hub', 'data-sources'],
    ['customers', 'products', 'orders', 'shipment-records', 'materials', 'approval-hub', 'persy-knowledge'],
    {
      products: '工程服务目录',
      customers: '客户管理',
      orders: '工程订单',
      'shipment-records': '履约记录',
      materials: '工程物料',
      'approval-hub': '工程审批',
      'data-sources': '工程数据源',
    },
    ['项目进度', '工程合同', '成本核算'],
  ),
  technology: profile(
    'technology',
    ['customers', 'products', 'orders', 'shipment-records', 'approval-hub', 'data-sources'],
    ['customers', 'products', 'orders', 'shipment-records', 'persy-knowledge', 'approval-hub', 'business-docking'],
    {
      customers: '客户管理',
      products: '服务产品',
      orders: '服务订单',
      'shipment-records': '交付记录',
      'approval-hub': '交付审批',
      'data-sources': '业务数据源',
    },
    ['项目管理', '合同管理', '研发迭代'],
  ),
  'business-services': profile(
    'business-services',
    ['customers', 'products', 'orders', 'shipment-records', 'approval-hub', 'data-sources'],
    ['customers', 'products', 'orders', 'shipment-records', 'persy-knowledge', 'approval-hub', 'business-docking'],
    {
      customers: '客户管理',
      products: '服务目录',
      orders: '服务订单',
      'shipment-records': '服务记录',
      'approval-hub': '业务审批',
      'data-sources': '业务数据源',
    },
    ['项目管理', '合同管理', '工时管理'],
  ),
  'consumer-services': profile(
    'consumer-services',
    ['products', 'customers', 'orders', 'shipment-records', 'approval-hub', 'data-sources'],
    ['products', 'customers', 'orders', 'shipment-records', 'persy-knowledge', 'approval-hub'],
    {
      products: '服务项目',
      customers: '客户管理',
      orders: '服务订单',
      'shipment-records': '服务记录',
      'approval-hub': '业务审批',
      'data-sources': '经营数据源',
    },
    ['门店管理', '预约排班', '会员体系'],
  ),
  'health-education': profile(
    'health-education',
    ['products', 'customers', 'orders', 'shipment-records', 'approval-hub', 'data-sources'],
    ['products', 'customers', 'orders', 'shipment-records', 'persy-knowledge', 'approval-hub'],
    {
      products: '服务项目',
      customers: '客户管理',
      orders: '服务订单',
      'shipment-records': '服务记录',
      'approval-hub': '业务审批',
      'data-sources': '业务数据源',
    },
    ['患者或学员档案', '诊疗或教务流程', '预约排课'],
  ),
  'agriculture-energy': profile(
    'agriculture-energy',
    ['products', 'materials', 'inventory', 'customers', 'orders', 'shipment-records', 'approval-hub', 'data-sources'],
    ['products', 'materials', 'inventory', 'orders', 'shipment-records', 'customers', 'persy-knowledge'],
    {
      products: '产品管理',
      materials: '物料与投入品',
      inventory: '库存管理',
      customers: '客户管理',
      orders: '销售订单',
      'shipment-records': '生产与交付记录',
      'approval-hub': '业务审批',
      'data-sources': '生产数据源',
    },
    ['农事或巡检计划', '设备维保', '安全监测'],
  ),
  'public-organizations': profile(
    'public-organizations',
    ['products', 'customers', 'orders', 'shipment-records', 'approval-hub', 'data-sources'],
    ['products', 'customers', 'orders', 'shipment-records', 'approval-hub', 'persy-knowledge', 'business-docking'],
    {
      products: '服务目录',
      customers: '往来单位',
      orders: '业务单据',
      'shipment-records': '办理记录',
      'approval-hub': '事项审批',
      'data-sources': '公共数据源',
    },
    ['事项全流程', '公共资产', '政策兑现'],
  ),
}

const onboardingCategoryByIndustryId = new Map(ONBOARDING_INDUSTRY_OPTIONS.map((item) => [item.id, item.categoryId]))

const FINE_GRAINED_INDUSTRY_PROFILES: Record<string, Partial<IndustryNavigationProfile>> = {
  通用: {
    menuLabels: {
      products: '业务对象',
      customers: '组织管理',
      orders: '业务单据',
      'shipment-records': '业务记录',
      'approval-hub': '审批工作台',
      'data-sources': '数据来源',
    },
  },
  涂料: {
    businessMenuKeys: ['products', 'materials', 'inventory', 'customers', 'orders', 'shipment-records', 'data-sources', 'print', 'template-preview'],
    previewMenuKeys: ['products', 'materials', 'inventory', 'orders', 'shipment-records', 'customers', 'print'],
    menuLabels: {
      products: '产品管理',
      materials: '原材料仓库',
      inventory: '库存管理',
      customers: '客户管理',
      orders: '出货单管理',
      'shipment-records': '出货记录',
      'data-sources': '经营数据源',
      print: '标签打印',
      'template-preview': '标签模板',
    },
    deferredCapabilities: ['配方管理', '批次质检', '生产工单'],
  },
  考勤: {
    businessMenuKeys: ['erp-hr', 'business-docking', 'data-sources', 'print', 'template-preview'],
    previewMenuKeys: ['erp-hr', 'business-docking', 'print'],
    menuLabels: {
      'erp-hr': '人事考勤',
      'data-sources': '考勤数据源',
      print: '考勤表打印',
      'template-preview': '考勤模板库',
    },
    deferredCapabilities: ['薪酬核算', '招聘管理'],
  },
  批发: {
    menuLabels: { products: '商品管理', customers: '客户管理', orders: '批发单', 'shipment-records': '出货记录', print: '单据打印' },
  },
  电商: {
    menuLabels: { products: '商品管理', customers: '买家管理', orders: '订单管理', 'shipment-records': '出货记录', print: '面单打印' },
  },
  餐饮: {
    businessMenuKeys: ['products', 'materials', 'inventory', 'customers', 'orders', 'shipment-records', 'data-sources', 'print'],
    previewMenuKeys: ['products', 'materials', 'inventory', 'orders', 'customers', 'shipment-records', 'print'],
    menuLabels: {
      products: '菜品与食材',
      materials: '食材仓库',
      inventory: '食材库存',
      customers: '供应商',
      orders: '订货单',
      'shipment-records': '收货记录',
      print: '食材标签',
    },
  },
  物流: {
    businessMenuKeys: ['products', 'customers', 'orders', 'shipment-records', 'data-sources', 'print', 'template-preview'],
    previewMenuKeys: ['products', 'customers', 'orders', 'shipment-records', 'data-sources', 'print', 'persy-knowledge'],
    menuLabels: {
      products: '货物管理',
      customers: '收发方',
      orders: '运单管理',
      'shipment-records': '发运记录',
      'data-sources': '物流数据源',
      print: '运单打印',
      'template-preview': '运单模板',
    },
  },
}

function cloneProfile(source: IndustryNavigationProfile): IndustryNavigationProfile {
  return {
    ...source,
    businessMenuKeys: [...source.businessMenuKeys],
    previewMenuKeys: [...source.previewMenuKeys],
    menuLabels: { ...source.menuLabels },
    deferredCapabilities: [...source.deferredCapabilities],
  }
}

export function resolveIndustryNavigationProfile(industryId: string): IndustryNavigationProfile {
  const id = String(industryId || '').trim()
  const categoryId = Object.prototype.hasOwnProperty.call(INDUSTRY_NAVIGATION_PROFILES, id)
    ? id as OnboardingIndustryCategoryId
    : onboardingCategoryByIndustryId.get(id) || 'business-services'
  const base = cloneProfile(INDUSTRY_NAVIGATION_PROFILES[categoryId])
  const fineGrained = FINE_GRAINED_INDUSTRY_PROFILES[id]
  if (!fineGrained) return { ...base, id: id || base.id }
  return {
    ...base,
    ...fineGrained,
    id: id || base.id,
    categoryId: base.categoryId,
    categoryLabel: base.categoryLabel,
    businessMenuKeys: withDefaultErpFoundation(fineGrained.businessMenuKeys || base.businessMenuKeys),
    previewMenuKeys: withDefaultErpFoundation(fineGrained.previewMenuKeys || base.previewMenuKeys),
    menuLabels: { ...base.menuLabels, ...(fineGrained.menuLabels || {}) },
    deferredCapabilities: [...(fineGrained.deferredCapabilities || base.deferredCapabilities)],
  }
}

export function resolveIndustryNavigationLabel(industryId: string, menuKey: string): string {
  return String(resolveIndustryNavigationProfile(industryId).menuLabels[menuKey as IndustrySidebarPreviewKey] || '').trim()
}
