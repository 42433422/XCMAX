/** 全站页面知识库：官网静态页 + MODstore 路由（管家 / SEO / 关键词应答共用） */

export const CORP_LINKS = {
  home: '/index.html',
  about: '/about.html',
  services: '/services.html',
  solutions: '/solutions.html',
  cases: '/cases.html',
  caseManufacture: '/case-manufacture.html',
  casePark: '/case-park.html',
  caseEdu: '/case-edu.html',
  news: '/news.html',
  honors: '/honors.html',
  contact: '/contact.html',
  excelToAi: '/excel-to-ai.html',
  market: '/market/',
} as const

export type IntakeTaskType = 'intake_fill' | 'intake_step' | 'intake_review' | 'navigate'

export interface QuickAction {
  label: string
  message?: string
  task?: IntakeTaskType
  payload?: { stepId?: string; prompt?: string; href?: string }
}

export interface PageKnowledge {
  pageId: string
  title: string
  description: string
  /** KiKi 欢迎区主标题 */
  welcomeTitle?: string
  /** 管家空状态欢迎语（省略则用 summary 首句） */
  welcomeDesc?: string
  summary: string
  highlights: string[]
  quickActions: QuickAction[]
}

const CORP_DEFAULT_WELCOME_TITLE = 'Hi，我是修茈科技 AI 管家'

const CORP_CONTACT_NAV: QuickAction = {
  label: '预约方案沟通',
  task: 'navigate',
  payload: { href: CORP_LINKS.contact },
}

const CORP_MARKET_NAV: QuickAction = {
  label: '进入 AI 市场',
  task: 'navigate',
  payload: { href: CORP_LINKS.market },
}

const CORP_PAGES: Record<string, PageKnowledge & { paths: string[] }> = {
  home: {
    pageId: 'home',
    paths: ['/', '/index.html', '/index'],
    title: '成都修茈科技有限公司 | XCAGI 企业 AI 自动化',
    description:
      '成都修茈科技有限公司专注 AI 单据智能处理、Excel 识别、标签打印、出货收货管理和企业流程自动化，帮助中小企业把业务数据真正跑起来。',
    welcomeTitle: 'Hi，想了解修茈能帮您做什么？',
    welcomeDesc: '我可以介绍产品矩阵，并引导您查看行业方案、客户案例或预约沟通。',
    summary:
      '官网首页展示修茈科技产品矩阵：AI Excel 单据识别、标签打印与库存记录、MODstore 智能体市场，以及制造、园区、教育等场景案例入口。',
    highlights: ['AI Excel Helper 单据识别', '标签打印与收发货记录', 'MODstore AI 工作台', '预约方案沟通'],
    quickActions: [
      { label: '介绍产品矩阵', message: '你们有哪些产品？' },
      { label: '查看行业解决方案', message: '有哪些行业解决方案？' },
      { label: '看看客户案例', message: '有哪些客户案例？' },
      CORP_CONTACT_NAV,
      CORP_MARKET_NAV,
    ],
  },
  about: {
    pageId: 'about',
    paths: ['/about.html'],
    title: '关于修茈 | 成都修茈科技有限公司',
    description:
      '了解成都修茈科技有限公司：专注 AI 单据处理、企业流程自动化与 XCAGI 工作台，为中小企业提供可落地的数字化方案。',
    welcomeTitle: 'Hi，想了解修茈科技是谁？',
    welcomeDesc: '本页介绍公司定位、XCAGI 工作台与 MODstore 的关系，可问我如何开始试用。',
    summary:
      '成都修茈科技（XCAGI）专注中小企业 AI 自动化：从单据识别到工作台与智能体市场，强调可落地实施与持续迭代。',
    highlights: ['公司定位与团队方向', 'XCAGI 工作台能力', '与 MODstore 智能体市场衔接'],
    quickActions: [
      { label: '公司是做什么的', message: '修茈科技是做什么的？' },
      { label: '有哪些产品能力', message: '你们有哪些产品？' },
      { label: '如何开始试用', message: '怎么注册或试用 AI 市场？' },
      CORP_CONTACT_NAV,
      CORP_MARKET_NAV,
    ],
  },
  services: {
    pageId: 'services',
    paths: ['/services.html'],
    title: '产品中心 | 成都修茈科技有限公司',
    description:
      '修茈科技产品中心：AI Excel Helper、标签打印、出货收货管理、微信消息自动化、知识库与 AI 工作流。',
    welcomeTitle: 'Hi，想了解哪类产品？',
    welcomeDesc: '可问我各产品线适用场景，或带您看行业方案与预约沟通。',
    summary:
      '产品中心涵盖 AI Excel 单据识别、标签打印与库存、出货收货、微信自动化、知识库与 MODstore 智能体市场等可组合能力。',
    highlights: ['AI Excel Helper', '标签打印与库存', 'MODstore 市场', '微信与知识库自动化'],
    quickActions: [
      { label: 'AI Excel 单据识别', message: 'AI Excel 单据识别能做什么？' },
      { label: '标签打印与库存', message: '标签打印和库存记录怎么用？' },
      { label: '看行业解决方案', message: '有哪些行业解决方案？' },
      CORP_CONTACT_NAV,
      CORP_MARKET_NAV,
    ],
  },
  solutions: {
    pageId: 'solutions',
    paths: ['/solutions.html'],
    title: '解决方案 | 成都修茈科技有限公司',
    description:
      '修茈科技解决方案覆盖制造贸易单据处理、园区服务协同、教育移动服务和企业 AI 工作流。',
    welcomeTitle: 'Hi，您的行业是哪种场景？',
    welcomeDesc: '可按制造贸易、园区、教育等方向了解方案，并查看对应案例。',
    summary:
      '解决方案覆盖制造贸易单据与库存协同、园区企业服务、教育移动服务，以及企业级 AI 工作流编排。',
    highlights: ['制造与贸易', '园区综合服务', '教育协同', 'AI 工作流'],
    quickActions: [
      { label: '制造贸易怎么落地', message: '制造贸易场景怎么落地？' },
      { label: '园区综合服务', message: '园区企业服务平台案例' },
      { label: '校园移动服务', message: '校园移动服务案例' },
      { label: '了解产品能力', message: '你们有哪些产品？' },
      CORP_CONTACT_NAV,
    ],
  },
  cases: {
    pageId: 'cases',
    paths: ['/cases.html'],
    title: '客户案例 | 成都修茈科技有限公司',
    description:
      '修茈科技案例中心：制造企业生产协同、园区企业服务平台、校园移动服务与业务协同。',
    welcomeTitle: 'Hi，想看看哪类客户实践？',
    welcomeDesc: '案例中心汇总制造、园区、教育等方向，可指定行业让我推荐详情。',
    summary: '案例中心展示制造生产协同、园区企业服务平台、校园移动服务等方向的实践摘要与详情链接。',
    highlights: ['制造生产协同', '园区服务平台', '校园移动服务'],
    quickActions: [
      { label: '制造生产协同案例', message: '制造企业案例详情' },
      { label: '园区服务平台案例', message: '园区企业服务平台案例' },
      { label: '校园移动服务案例', message: '校园移动服务案例' },
      { label: '了解产品与方案', message: '你们有哪些产品？' },
      CORP_CONTACT_NAV,
    ],
  },
  'case-manufacture': {
    pageId: 'case-manufacture',
    paths: ['/case-manufacture.html'],
    title: '案例详情 - 生产协同与库存管理 | 成都修茈科技有限公司',
    description:
      '制造企业生产协同与库存管理案例，围绕生产计划、库存数据、报表分析和跨部门协同进行系统化建设。',
    welcomeTitle: 'Hi，想了解制造协同案例？',
    welcomeDesc: '本页介绍生产计划、库存、报表与跨部门协同，可问挑战、方案或如何复用到您企业。',
    summary:
      '制造案例：围绕生产计划、仓储库存、报表分析与跨部门协同建设一体化系统，降低重复录入与错漏。',
    highlights: ['生产计划协同', '库存数据统一', '报表分析', '跨部门流程'],
    quickActions: [
      { label: '案例解决了什么问题', message: '这个制造案例解决了什么问题？' },
      { label: '方案怎么落地', message: '制造贸易场景怎么落地？' },
      { label: '更多客户案例', message: '有哪些客户案例？' },
      CORP_CONTACT_NAV,
      { label: '了解产品能力', message: '你们有哪些产品？' },
    ],
  },
  'case-park': {
    pageId: 'case-park',
    paths: ['/case-park.html'],
    title: '案例详情 - 园区企业综合服务平台 | 成都修茈科技有限公司',
    description:
      '园区企业综合服务平台案例，建设企业服务、事项办理、统计分析和领导驾驶舱等能力。',
    welcomeTitle: 'Hi，想了解园区服务案例？',
    welcomeDesc: '本页介绍企业服务、事项办理、统计与领导驾驶舱，可问实施路径或预约交流。',
    summary: '园区案例：整合企业服务、事项办理、数据统计与领导驾驶舱，提升园区数字化管理效率。',
    highlights: ['企业服务入口', '事项办理', '统计分析', '领导驾驶舱'],
    quickActions: [
      { label: '案例亮点是什么', message: '园区企业服务平台案例' },
      { label: '如何在我们园区复用', message: '园区方案怎么在我们园区落地？' },
      { label: '更多客户案例', message: '有哪些客户案例？' },
      CORP_CONTACT_NAV,
      { label: '了解产品能力', message: '你们有哪些产品？' },
    ],
  },
  'case-edu': {
    pageId: 'case-edu',
    paths: ['/case-edu.html'],
    title: '案例详情 - 校园移动服务与业务协同 | 成都修茈科技有限公司',
    description:
      '校园移动服务与业务协同案例，整合通知、审批、服务申请和统计分析，提升师生服务体验。',
    welcomeTitle: 'Hi，想了解校园服务案例？',
    welcomeDesc: '本页介绍通知、审批、服务申请与统计，可问适用学校类型或对接方式。',
    summary: '教育案例：统一通知、审批、服务申请与数据统计，改善师生服务体验与管理效率。',
    highlights: ['移动服务入口', '审批流程', '服务申请', '数据统计'],
    quickActions: [
      { label: '案例适用哪些学校', message: '校园移动服务案例' },
      { label: '教育场景怎么落地', message: '教育场景怎么落地？' },
      { label: '更多客户案例', message: '有哪些客户案例？' },
      CORP_CONTACT_NAV,
      { label: '了解产品能力', message: '你们有哪些产品？' },
    ],
  },
  news: {
    pageId: 'news',
    paths: ['/news.html'],
    title: '新闻资讯 | 成都修茈科技有限公司',
    description:
      '修茈科技新闻资讯与行业观察：企业 AI 自动化、单据处理、Agent 趋势与中小企业数字化。',
    welcomeTitle: 'Hi，想了解最新动态？',
    welcomeDesc: '可问公司新闻、行业观察，或带您看产品与预约沟通。',
    summary: '新闻资讯栏目提供公司动态、产品更新与行业观察，帮助了解 AI 自动化与单据处理趋势。',
    highlights: ['公司动态', '行业观察', '产品更新'],
    quickActions: [
      { label: '最新公司动态', message: '修茈科技最近有什么动态？' },
      { label: '行业与 AI 趋势', message: '企业 AI 自动化有什么趋势？' },
      { label: '了解产品', message: '你们有哪些产品？' },
      CORP_CONTACT_NAV,
      CORP_MARKET_NAV,
    ],
  },
  honors: {
    pageId: 'honors',
    paths: ['/honors.html'],
    title: '资质与能力 | 成都修茈科技有限公司',
    description:
      '成都修茈科技有限公司能力说明：软件开发、项目实施、信息安全、服务机制和持续迭代能力。',
    welcomeTitle: 'Hi，想了解合作保障？',
    welcomeDesc: '本页说明研发、交付、安全与服务机制（以实际公示为准），可问资质或预约沟通。',
    summary:
      '能力说明涵盖软件开发、项目实施、信息安全、服务机制与持续迭代；具体资质证照以实际公示为准。',
    highlights: ['软件开发能力', '项目实施', '信息安全', '服务与迭代机制'],
    quickActions: [
      { label: '交付与服务机制', message: '修茈科技的服务和交付机制是怎样的？' },
      { label: '信息安全能力', message: '你们的信息安全能力如何？' },
      { label: '有哪些产品', message: '你们有哪些产品？' },
      CORP_CONTACT_NAV,
      CORP_MARKET_NAV,
    ],
  },
  contact: {
    pageId: 'contact',
    paths: ['/contact.html'],
    title: '联系我们 | 成都修茈科技有限公司',
    description:
      '联系成都修茈科技有限公司，咨询 AI 单据处理、企业自动化、MODstore 智能体市场和数字化解决方案。',
    welcomeTitle: 'Hi，我来帮您填需求问卷',
    welcomeDesc:
      '告诉我公司与系统类型，我可一键预填右侧问卷，您简单改改就能提交。',
    summary:
      '联系我们页提供预约方案沟通表单，可说明单据识别、标签打印、AI 工作台等需求，我们会尽快回复。',
    highlights: ['预约方案沟通', '场景需求说明', '销售与技术支持入口'],
    quickActions: [
      {
        label: 'AI 一键填好问卷',
        task: 'intake_fill',
        message: '请根据公司与系统类型帮我预填问卷',
      },
      {
        label: '贸易公司 + Excel 跟单示例',
        task: 'intake_fill',
        payload: {
          prompt:
            '公司：示例贸易有限公司\n主要系统/业务：Excel 跟单\n\n请根据该公司与系统类型的典型业务场景，完整预填联系页需求问卷。draft 中 company 填「示例贸易有限公司」。不要编造手机、邮箱、姓名。',
        },
      },
      { label: '跳到联系方式', task: 'intake_step', payload: { stepId: 'contact' } },
      { label: '提交前帮我核对', task: 'intake_review' },
    ],
  },
  'excel-to-ai': {
    pageId: 'excel-to-ai',
    paths: ['/excel-to-ai.html'],
    title: 'Excel → AI 上传工具 | 成都修茈科技有限公司',
    description:
      '在线体验 AI Excel 单据识别：上传出货单、收货单等表格，自动提取关键字段，了解修茈科技单据处理能力。',
    welcomeTitle: 'Hi，想体验 Excel 识别？',
    welcomeDesc: '本页可上传表格试识别；完整流程与打印联动见产品中心，也可预约方案沟通。',
    summary:
      'Excel → AI 工具页用于快速体验表格单据识别，提取产品、数量、价格等字段，完整能力见 AI Excel Helper 与产品中心。',
    highlights: ['上传 Excel 体验', '字段自动提取', '对接完整产品线'],
    quickActions: [
      { label: '上传工具怎么用', message: 'Excel 上传工具怎么用？' },
      { label: '完整单据识别能力', message: 'AI Excel 单据识别能做什么？' },
      {
        label: '查看产品中心',
        task: 'navigate',
        payload: { href: CORP_LINKS.services },
      },
      CORP_CONTACT_NAV,
      CORP_MARKET_NAV,
    ],
  },
  'market-about': {
    pageId: 'market-about',
    paths: [],
    title: 'XC AGI 市场 | 智能员工与 AI 工作台',
    description:
      '修茈科技 AI 市场：组合 Mod 与 AI 员工，处理单据、流程与报表；支持注册试用与进入工作台。',
    welcomeDesc: '这是 AI 市场公开介绍页。可了解智能员工能力，或引导您注册、查看会员方案。',
    summary:
      'AI 市场落地页介绍可复制的智能员工团队：单据识别、自动化处理、7×24 运行与多行业场景，可注册进入工作台。',
    highlights: ['智能单据识别', '自动化处理', '7×24 AI 员工', '免费注册试用'],
    quickActions: [
      { label: '有哪些能力', message: 'AI 市场有什么功能？' },
      { label: '会员方案', message: '会员和价格怎么样？' },
      { label: '免费注册', message: '怎么注册账号？' },
      { label: '官网产品', message: '你们有哪些产品？' },
      { label: '联系咨询', message: '怎么联系你们？' },
      { label: '本页介绍', message: '这个页面有什么功能？' },
    ],
  },
}

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

export function isContactPagePath(pathname: string): boolean {
  return /\/contact(?:\.html)?\/?$/i.test(pathname || '')
}

export function resolveCorpPageId(pathname: string): string {
  const p = pathname.replace(/\/$/, '') || '/'
  for (const page of Object.values(CORP_PAGES)) {
    if (page.paths.some((path) => path === p || (path === '/' && (p === '/' || p.endsWith('/index.html'))))) {
      return page.pageId
    }
  }
  if (p === '' || p === '/' || /index\.html$/i.test(p)) return 'home'
  return 'home'
}

export function getCorpPageKnowledge(pageId?: string, pathname?: string): PageKnowledge {
  const id = pageId || (pathname ? resolveCorpPageId(pathname) : 'home')
  const raw = CORP_PAGES[id] || CORP_PAGES.home
  const { paths: _paths, ...rest } = raw
  return rest
}

export function getMarketPageKnowledge(routeName?: string | null): PageKnowledge | null {
  if (!routeName) return null
  return MARKET_ROUTES[routeName] ?? null
}

export function getCorpWelcomeDesc(pathname: string): string {
  const page = getCorpPageKnowledge(undefined, pathname)
  return page.welcomeDesc || page.summary
}

export function getCorpWelcomeTitle(pathname: string): string {
  const page = getCorpPageKnowledge(undefined, pathname)
  return page.welcomeTitle || CORP_DEFAULT_WELCOME_TITLE
}

export function getCorpQuickActions(pathname: string): QuickAction[] {
  return getCorpPageKnowledge(undefined, pathname).quickActions
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

export function getStructuredPageSummary(opts: {
  corpPathname?: string
  routeName?: string | null
  domExcerpt?: string
}): string {
  const corp =
    opts.corpPathname != null ? getCorpPageKnowledge(undefined, opts.corpPathname) : null
  const market = opts.routeName ? getMarketPageKnowledge(opts.routeName) : null
  const page = market || corp
  if (!page) return opts.domExcerpt?.slice(0, 800) || ''
  const bullets = page.highlights.map((h) => `• ${h}`).join('\n')
  let text = `${page.summary}\n\n要点：\n${bullets}`
  if (opts.domExcerpt?.trim()) {
    text += `\n\n页面可见内容（节选）：\n${opts.domExcerpt.slice(0, 400)}`
  }
  return text.slice(0, 1200)
}

export function linkForCorpPage(pageId: string): string {
  const map: Record<string, string> = {
    home: CORP_LINKS.home,
    about: CORP_LINKS.about,
    services: CORP_LINKS.services,
    solutions: CORP_LINKS.solutions,
    cases: CORP_LINKS.cases,
    'case-manufacture': CORP_LINKS.caseManufacture,
    'case-park': CORP_LINKS.casePark,
    'case-edu': CORP_LINKS.caseEdu,
    news: CORP_LINKS.news,
    honors: CORP_LINKS.honors,
    contact: CORP_LINKS.contact,
    'excel-to-ai': CORP_LINKS.excelToAi,
    'market-about': CORP_LINKS.market,
  }
  return map[pageId] || CORP_LINKS.home
}
