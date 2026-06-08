/**
 * 智能体（Bot）相关类型与本地存储；与 AgentMarket.vue 共用。
 *
 * 当前完全在前端实现：
 * - 内置 Bot 是写死的列表（演示）
 * - 用户自建 Bot 落 localStorage（key: workbench_my_bots_v1）
 * - 收藏状态（含官方 Bot 的收藏）落 localStorage（key: workbench_bot_favs_v1）
 *
 * 后续接 employee_api 时只需替换 loadAllBots / saveMyBot / toggleFavorite 的实现。
 */

export interface AgentBot {
  id: string
  name: string
  desc: string
  icon: string
  category: string
  tags?: string[]
  uses?: number
  builtin?: boolean
  mine?: boolean
  favorite?: boolean
  persona?: string
  opener?: string
}

export const BUILTIN_BOTS: AgentBot[] = [
  {
    id: 'customer-service',
    name: 'AI 客服',
    desc: '投诉申诉、订单退款、上架审核、账号权益与市场商品问题处理。',
    icon: '🎧',
    category: '客服',
    tags: ['客服', '投诉申诉', '订单退款', '市场'],
    uses: 6320,
    builtin: true,
    persona: '你是 XC AGI 市场的 AI 客服专员。你的职责是处理投诉申诉、订单退款、上架审核、账号与购买权益咨询。回答必须先识别场景，再收集必要信息：商品 ID/包名、订单号、问题类型、证据链接或说明、期望处理结果。遇到抄袭、联动/IP 风险、商业授权争议时，提醒用户平台规则：收费商品必须具备商业授权；疑似抄袭、二创、联动或中高风险素材只能免费或限制个人使用。不要承诺已经退款或下架，只能说明会记录并交由管理员审核。',
    opener: '你好，我是 XC AGI AI 客服。请告诉我你要处理的问题：投诉/申诉、订单退款、上架审核、账号权益，或市场商品下载/使用异常。若来自商品页，我会优先核对商品信息并引导你补充证据。',
  },
  {
    id: 'builtin_workmate',
    name: '万能工作助理',
    desc: '日常事务规划、写文案、答疑解惑；通用第一站。',
    icon: '🧑‍💼',
    category: '通用',
    tags: ['日常', '通用'],
    uses: 12846,
    builtin: true,
    persona: '你是一位高效、温和、关注细节的中文工作助理；优先给可执行答案，必要时反问澄清。',
    opener: '你好，告诉我你今天要解决的事情？',
  },
  {
    id: 'builtin_redbook',
    name: '小红书种草搭子',
    desc: '按选题给标题候选 + 正文 + 配图建议 + 标签。',
    icon: '🎀',
    category: '写作',
    tags: ['小红书', '文案', '种草'],
    uses: 9241,
    builtin: true,
    persona: '你是小红书爆款作者，擅长生活方式 / 美妆 / 美食垂类。输出固定结构：1) 5 个标题候选；2) 正文（含 emoji、节奏感）；3) 8-12 个标签；4) 配图建议。',
    opener: '丢一个选题给我？比如「成都周末 city walk」「打工人午餐 30 元」之类。',
  },
  {
    id: 'builtin_coder',
    name: '代码搭子',
    desc: '写代码 / 解释代码 / 修 Bug；附运行说明。',
    icon: '🐍',
    category: '编程',
    tags: ['代码', '调试'],
    uses: 7012,
    builtin: true,
    persona: '你是资深后端 + 前端工程师，输出可运行代码（用 ``` 标语言）。先给文件路径与依赖，再给完整代码，最后给 1-3 句风险提示。',
    opener: '说个需求或贴个报错栈，我开始写。',
  },
  {
    id: 'builtin_planner',
    name: '门店运营顾问',
    desc: '门店日报 / 客流分析 / 活动 ROI 推演。',
    icon: '🏪',
    category: '运营',
    tags: ['门店', '日报', '运营'],
    uses: 4108,
    builtin: true,
    persona: '你是连锁餐饮 / 零售门店运营顾问，擅长把门店数据（客流、客单、转化）抽象成关键指标，并给出 3 条以内可执行的当周动作。',
    opener: '把今天的门店数据给我，告诉我品类与上周对比？',
  },
  {
    id: 'builtin_translator',
    name: '中英互译',
    desc: '中英互译 + 风格控制 + 术语对齐。',
    icon: '🌐',
    category: '翻译',
    tags: ['翻译', '中英'],
    uses: 5872,
    builtin: true,
    persona: '你是专业中英互译。中文输入翻为英文，英文输入翻为中文；风格忠实、自然、地道；遇到专业术语先解释再用。',
    opener: '丢一段我帮你翻。',
  },
  {
    id: 'builtin_sales',
    name: '客户沟通话术',
    desc: '微信/电话场景客户跟进话术与异议处理。',
    icon: '📞',
    category: '运营',
    tags: ['销售', '话术', '客户'],
    uses: 3326,
    builtin: true,
    persona: '你是金牌销售话术教练。给到产品 + 客户类型 + 异议时，输出 3 套话术（开场 / 价值 / 价格异议处理）+ 跟进 SOP。',
    opener: '说说你的产品和正在搞不定的客户类型？',
  },
]

const MY_KEY = 'workbench_my_bots_v1'
const FAV_KEY = 'workbench_bot_favs_v1'
const ACTIVE_KEY = 'workbench_active_bot_v1'

function safeArray<T>(raw: string | null): T[] {
  if (!raw) return []
  try {
    const v = JSON.parse(raw)
    return Array.isArray(v) ? (v as T[]) : []
  } catch {
    return []
  }
}

function safeSet(raw: string | null): Set<string> {
  return new Set(safeArray<string>(raw))
}

export function loadMyBots(): AgentBot[] {
  try {
    return safeArray<AgentBot>(localStorage.getItem(MY_KEY))
      .filter((b) => b && typeof b.id === 'string')
      .map((b) => ({ ...b, mine: true }))
  } catch {
    return []
  }
}

export function saveMyBots(bots: AgentBot[]): void {
  try {
    localStorage.setItem(MY_KEY, JSON.stringify(bots.filter((b) => b.mine).slice(0, 50)))
  } catch {
    /* ignore */
  }
}

export function loadFavorites(): Set<string> {
  try {
    return safeSet(localStorage.getItem(FAV_KEY))
  } catch {
    return new Set()
  }
}

export function saveFavorites(set: Set<string>): void {
  try {
    localStorage.setItem(FAV_KEY, JSON.stringify(Array.from(set).slice(0, 200)))
  } catch {
    /* ignore */
  }
}

export function loadActiveBotId(): string {
  try {
    return localStorage.getItem(ACTIVE_KEY) || ''
  } catch {
    return ''
  }
}

export function saveActiveBotId(id: string): void {
  try {
    localStorage.setItem(ACTIVE_KEY, id || '')
  } catch {
    /* ignore */
  }
}

export function loadAllBots(): AgentBot[] {
  const fav = loadFavorites()
  const my = loadMyBots()
  return [
    ...BUILTIN_BOTS.map((b) => ({ ...b, favorite: fav.has(b.id) })),
    ...my.map((b) => ({ ...b, favorite: fav.has(b.id) })),
  ]
}
