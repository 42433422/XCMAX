import type { TutorialStep } from './types'
import { createStep } from './stepFactory'

/** 进阶教程末尾：智能生态 → AI 市场 → 员工 → 办公员工包 */
export function buildOfficeEmployeePackSteps(): TutorialStep[] {
  return [
    createStep({
      id: 'office-pack-ecosystem-nav',
      title: '智能生态 · 入口',
      description: '办公员工包（CSV/Excel/PDF 等表格类 AI 员工）是软件的基础能力，也适合教学演示。请先点击侧栏「智能生态」。',
      targetSelector: '.sidebar .menu-item[data-view="ai-ecosystem"]',
      actionType: 'click',
      routeName: 'ai-ecosystem',
      track: 'advanced',
    }),
    createStep({
      id: 'office-pack-open-modstore',
      title: 'AI 市场',
      description: '在智能生态首页点击「AI 市场」，在「员工」页浏览与安装办公员工；「模块」页可浏览业务扩展。',
      routeName: 'ai-ecosystem',
      targetSelector: '[data-tour="ecosystem-launcher-modstore"]',
      highlightSelector: '[data-tour="ecosystem-launcher-modstore"]',
      actionType: 'click',
      track: 'advanced',
    }),
    createStep({
      id: 'office-pack-nav-tab',
      title: '办公员工包',
      description: '在「员工」页选择「办公员工包」分类。装齐后即可在对话中使用对应工具，无需重启。',
      routeName: 'mod-store',
      routeQuery: { type: 'employee', tab: 'office' },
      targetSelector: '[data-tour="store-nav-office"]',
      highlightSelector: '[data-tour="store-nav-office"]',
      actionType: 'click',
      track: 'advanced',
    }),
    createStep({
      id: 'office-pack-one-click',
      title: '一键安装并入驻',
      description: '点击「一键安装并入驻」装齐 10 个办公员工。安装完成后系统会热加载 HTTP 路由与 Planner 工具注册表。',
      routeName: 'mod-store',
      routeQuery: { type: 'employee', tab: 'office' },
      targetSelector: '[data-tour="store-one-click-install"]',
      highlightSelector: '[data-tour="store-one-click-install"]',
      actionType: 'click',
      track: 'advanced',
    }),
    createStep({
      id: 'office-pack-wait-ready',
      title: '等待员工工具就绪',
      description: '正在安装并注册 Planner 工具… 装齐后可在智能对话中读取 CSV/Excel 等文件。',
      routeName: 'mod-store',
      routeQuery: { type: 'employee', tab: 'office' },
      targetSelector: '[data-tour="store-shell"]',
      highlightSelector: '[data-tour="store-shell"]',
      actionType: 'observe',
      track: 'advanced',
      noAutoSkipWhenMissing: true,
    }),
    createStep({
      id: 'office-pack-chat-verify',
      title: '对话验收',
      description: '回到对话页，可尝试发送「读取这个 CSV 文件」等指令；Planner 应能看到并调用刚安装的办公员工工具。',
      routeName: 'chat',
      targetSelector: '[data-tour="chat-input-area"]',
      highlightSelector: '[data-tour="chat-input-area"]',
      actionType: 'observe',
      track: 'advanced',
    }),
  ]
}
