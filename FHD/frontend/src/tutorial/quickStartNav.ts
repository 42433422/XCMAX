/** 快速上手教程聚焦的侧栏入口（顺序即讲解顺序） */
export const QUICK_START_FOCUS_NAV_KEYS = [
  'chat',
  'ai-ecosystem',
  'employee-workflow',
  'im',
  'settings',
] as const

export type QuickStartNavKey = (typeof QUICK_START_FOCUS_NAV_KEYS)[number]

/** 侧栏 key → 页内高亮用的 vue-router name */
export const QUICK_START_PAGE_ROUTE: Partial<Record<QuickStartNavKey, string>> = {
  'employee-workflow': 'workflow-employee-space',
}

/** 侧栏入口解说：口语化、通用平台表述，避免行业专有词 */
export const QUICK_START_NAV_INTRO: Partial<Record<QuickStartNavKey, string>> = {
  chat: '平时跟助手说话、处理事情，基本都在这儿。右上角「副窗」里还有推送、协助和教程入口。',
  'ai-ecosystem':
    '装扩展能力的地方。这一步会带你去员工商店，把「办公员工包」装进 L1 工具层——在智能对话里读表格用，不是 L2 执行层工位。',
  'employee-workflow':
    '看各个自动小助手在哪儿、忙不忙；开关跟右侧「一键托管」连着。教程里装的办公包在 L1 工具层，L2 执行层要另装行业/履约类员工才有。',
  im: '站内跟别人发消息用这儿：左边选人，右边聊。',
  settings: '改助手名字、界面样式、账号信息；用模型前也在这儿看余额、充值。',
}
