/** MODstore 市场路由页面知识与访问器（原 siteKnowledge 单体拆分） */
import type { PageKnowledge, QuickAction } from './types'

const MARKET_ROUTES: Record<string, PageKnowledge> = {
  'workbench-home': {
    pageId: 'workbench-home',
    title: '工作台首页 | XC AGI',
    description: 'XC AGI 工作台：对话、员工与 Mod 编排入口。',
    summary: '工作台首页是登录后的主界面，可发起对话、管理 AI 员工与进入各工作台模块。',
    highlights: ['新对话', '员工与 Mod', '快捷进入各模块'],
    quickActions: [
      { label: '这页有什么', message: '这个页面有什么功能？' },
      { label: 'AI 市场', message: '去 AI 市场' },
      { label: '搜索员工', message: '帮我搜索 AI 员工' },
      { label: '会员方案', message: '去会员页面' },
      { label: '钱包余额', message: '查看钱包余额' },
    ],
  },
  'ai-store': {
    pageId: 'ai-store',
    title: 'AI 市场 | XC AGI',
    description: '浏览与选购 AI 员工、模板与能力包。',
    summary: 'AI 市场页可浏览、搜索并选购 AI 员工与相关能力，支持查看详情与加入工作台。',
    highlights: ['搜索员工', '分类浏览', '购买与试用'],
    quickActions: [
      { label: '搜索员工', message: '帮我搜索 AI 员工' },
      { label: '这页有什么', message: '这个页面有什么功能？' },
      { label: '去工作台', message: '去工作台首页' },
      { label: '会员方案', message: '去会员页面' },
      { label: '钱包', message: '打开钱包' },
    ],
  },
  plans: {
    pageId: 'plans',
    title: '会员方案 | XC AGI',
    description: '查看与购买 XC AGI 会员套餐。',
    summary: '会员方案页展示各档套餐权益与价格，支持选择方案并完成购买。',
    highlights: ['套餐对比', '权益说明', '购买开通'],
    quickActions: [
      { label: '会员方案', message: '介绍一下会员套餐' },
      { label: '去充值', message: '去充值页面' },
      { label: 'AI 市场', message: '去 AI 市场' },
      { label: '这页有什么', message: '这个页面有什么功能？' },
    ],
  },
  wallet: {
    pageId: 'wallet',
    title: '钱包 | XC AGI',
    description: '查看余额、消费记录与充值入口。',
    summary: '钱包页展示账户余额、消费明细，并可进入充值或已购内容。',
    highlights: ['余额查询', '消费记录', '充值入口'],
    quickActions: [
      { label: '去充值', message: '去充值页面' },
      { label: '已购内容', message: '查看已购 AI 员工' },
      { label: '会员方案', message: '去会员页面' },
      { label: '这页有什么', message: '这个页面有什么功能？' },
    ],
  },
  recharge: {
    pageId: 'recharge',
    title: '充值 | XC AGI',
    description: '为账户充值以使用 AI 能力与员工。',
    summary: '充值页可选择金额并完成支付，为后续调用 AI 员工与 LLM 提供余额。',
    highlights: ['选择金额', '支付方式', '到账余额'],
    quickActions: [
      { label: '查看钱包', message: '打开钱包' },
      { label: '会员方案', message: '去会员页面' },
      { label: '这页有什么', message: '这个页面有什么功能？' },
    ],
  },
  orders: {
    pageId: 'orders',
    title: '订单 | XC AGI',
    description: '查看购买订单与支付状态。',
    summary: '订单页列出历史购买记录与订单状态，便于核对会员与员工购买。',
    highlights: ['订单列表', '支付状态', '订单详情'],
    quickActions: [
      { label: 'AI 市场', message: '去 AI 市场' },
      { label: '钱包', message: '打开钱包' },
      { label: '这页有什么', message: '这个页面有什么功能？' },
    ],
  },
  templates: {
    pageId: 'templates',
    title: '模板 | XC AGI',
    description: '浏览工作流与场景模板。',
    summary: '模板页提供可复用的工作流与场景模板，便于快速搭建 AI 员工与流程。',
    highlights: ['模板分类', '预览说明', '应用到工作台'],
    quickActions: [
      { label: '去工作台', message: '去工作台首页' },
      { label: 'AI 市场', message: '去 AI 市场' },
      { label: '这页有什么', message: '这个页面有什么功能？' },
    ],
  },
  'developer-portal': {
    pageId: 'developer-portal',
    title: '开发者门户 | XC AGI',
    description: 'API、Mod 开发与集成文档入口。',
    summary: '开发者门户提供 API 与 Mod 开发相关入口，便于二次集成与扩展。',
    highlights: ['API 文档', 'Mod 开发', '集成说明'],
    quickActions: [
      { label: '去工作台', message: '去工作台首页' },
      { label: '账户设置', message: '打开账户设置' },
      { label: '这页有什么', message: '这个页面有什么功能？' },
    ],
  },
  account: {
    pageId: 'account',
    title: '账户设置 | XC AGI',
    description: '个人资料、LLM 配置与 API Key 管理。',
    summary: '账户设置页可修改资料、配置 LLM 供应商与 API Key，管理管家相关偏好。',
    highlights: ['个人资料', 'LLM 设置', 'API Key'],
    quickActions: [
      { label: '钱包', message: '打开钱包' },
      { label: '去工作台', message: '去工作台首页' },
      { label: '这页有什么', message: '这个页面有什么功能？' },
    ],
  },
  'workbench-shell': {
    pageId: 'workbench-shell',
    title: '工作台 | XC AGI',
    description: '编辑 Mod、工作流或 AI 员工。',
    summary: '工作台 Shell 用于编辑 Mod、工作流图或员工配置，是深度编排与调试入口。',
    highlights: ['Mod 编辑', '工作流', '员工配置'],
    quickActions: [
      { label: '去首页', message: '去工作台首页' },
      { label: 'AI 市场', message: '去 AI 市场' },
      { label: '这页有什么', message: '这个页面有什么功能？' },
    ],
  },
}

const MARKET_DEFAULT_QUICK: QuickAction[] = [
  { label: '这页有什么', message: '这个页面有什么功能？' },
  { label: '去会员页', message: '去会员页面' },
  { label: '搜索员工', message: '帮我搜索 AI 员工' },
  { label: 'AI 市场', message: '去 AI 市场' },
  { label: '钱包', message: '打开钱包' },
]

export function getMarketPageKnowledge(routeName?: string | null): PageKnowledge | null {
  if (!routeName) return null
  return MARKET_ROUTES[routeName] ?? null
}

export function getMarketQuickActions(routeName?: string | null): QuickAction[] {
  const page = getMarketPageKnowledge(routeName)
  return page?.quickActions ?? MARKET_DEFAULT_QUICK
}

export function getMarketWelcomeDesc(routeName?: string | null): string {
  const page = getMarketPageKnowledge(routeName)
  if (!page) return '我可以理解当前页面，并帮你跳转、搜索或执行常用操作。'
  return page.welcomeDesc || page.summary
}
