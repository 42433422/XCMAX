import type { TutorialPageHighlight } from './types'

/** 快速上手路线专用页内解说（覆盖 HOST_PAGE_HIGHLIGHTS 中同名路由，语气口语化、避免行业词） */
export const QUICK_START_PAGE_HIGHLIGHTS: Record<string, TutorialPageHighlight[]> = {
  chat: [
    {
      idSuffix: 'quick',
      title: '智能对话 · 快捷按钮',
      description: '上面这一排小按钮，点一下就能把常用说法填进输入框，不用自己从头打。',
      targetSelector: '#view-chat .quick-actions',
    },
    {
      idSuffix: 'thread',
      title: '智能对话 · 聊天记录',
      description: '中间是对话区：你发的、助手回的，都会按顺序排在这里。',
      targetSelector: '#view-chat .chat-container',
    },
    {
      idSuffix: 'input',
      title: '智能对话 · 输入区',
      description: '最底下打字、发消息；新开对话、看历史、上传表格等也在这附近。',
      targetSelector: '#view-chat .input-area',
    },
  ],
  'workflow-employee-space': [
    {
      idSuffix: 'head',
      title: '员工空间 · 总览',
      description: '这儿看各个自动小助手在哪儿、状态怎样，跟右侧副窗、对话页看到的是同一套。办公员工包在 L1 工具层，不会出现在 L2 执行层。',
      targetSelector: '#view-workflow-employee-space .ews-page-head',
    },
    {
      idSuffix: 'desks',
      title: '员工空间 · 工位卡片',
      description: '一格就是一个小助手：忙不忙、开不开，都可以在这里点；跟副窗里「一键托管」联动。',
      targetSelector: '[data-tour="employee-workspace-desks"]',
      highlightSelector: '[data-tour="employee-workspace-desks"]',
    },
  ],
  im: [
    {
      idSuffix: 'sidebar',
      title: '消息 · 会话列表',
      description: '左边是聊过的人；想新开聊天点铅笔图标。绿点亮着说明实时连接正常。',
      targetSelector: '[data-tour="im-sidebar"]',
      highlightSelector: '[data-tour="im-sidebar"]',
    },
    {
      idSuffix: 'thread',
      title: '消息 · 聊天内容',
      description: '选中左边某个人或群，右边就出现聊天记录，往上滑可以看更早的消息。',
      targetSelector: '[data-tour="im-chat-thread"]',
      highlightSelector: '[data-tour="im-chat-thread"]',
    },
    {
      idSuffix: 'compose',
      title: '消息 · 发消息',
      description: '底下输入框打好字，回车或点「发送」就发出去了；记得先在左边选一个会话。',
      targetSelector: '[data-tour="im-compose"]',
      highlightSelector: '[data-tour="im-compose"]',
    },
  ],
  settings: [
    {
      idSuffix: 'header',
      title: '系统设置 · 总览',
      description: '设置都分块放在这儿，往下翻就能看到不同类别的卡片。',
      targetSelector: '#view-settings .settings-page__hero',
    },
    {
      idSuffix: 'model-payment',
      title: '系统设置 · 看余额',
      description:
        '用助手、调模型都会花额度。展开「模型服务」，这儿能看还剩多少钱；旁边可以刷新、打开钱包或套餐。',
      targetSelector: '[data-tutorial-id="settings-model-payment"]',
      highlightSelector: '[data-tour="settings-model-balance"]',
    },
    {
      idSuffix: 'recharge',
      title: '系统设置 · 快捷充值',
      description:
        '余额不够就点「快捷充值」，选一个金额或套餐购买；付完款回到这页点「刷新」，数字就会更新。',
      targetSelector: '[data-tour="settings-quick-recharge"]',
      highlightSelector: '[data-tour="settings-quick-recharge"]',
    },
    {
      idSuffix: 'basic',
      title: '系统设置 · 常用项',
      description: '助手怎么称呼、界面长什么样、一些日常开关，多在「基本设置」里改。',
      targetSelector: '[data-tutorial-id="settings-basic"]',
    },
  ],
}
