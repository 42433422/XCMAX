import type { TutorialStep } from './types'
import { createStep } from './stepFactory'

/** 进阶教程末尾：能力库装齐办公 10 员工 + 对话验收 Planner 工具可见 */
export function buildOfficeEmployeePackSteps(): TutorialStep[] {
  return [
    createStep({
      id: 'office-pack-nav-tab',
      title: '能力库 · 办公员工包',
      description:
        'CSV/Excel/PDF 等表格类员工在「办公员工包」分类。装齐后 Planner 会自动加载对应工具（无需重启）。请点击左侧「办公员工包」。',
      routeName: 'mod-store',
      routeQuery: { tab: 'office' },
      targetSelector: '[data-tour="store-nav-office"]',
      highlightSelector: '[data-tour="store-nav-office"]',
      actionType: 'click',
      track: 'advanced',
    }),
    createStep({
      id: 'office-pack-one-click',
      title: '一键安装并入驻',
      description:
        '点击「一键安装并入驻」装齐 10 个办公员工。安装完成后系统会热加载 HTTP 路由与 Planner 工具注册表。',
      routeName: 'mod-store',
      routeQuery: { tab: 'office' },
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
      routeQuery: { tab: 'office' },
      targetSelector: '[data-tour="store-shell"]',
      highlightSelector: '[data-tour="store-shell"]',
      actionType: 'observe',
      track: 'advanced',
      noAutoSkipWhenMissing: true,
    }),
    createStep({
      id: 'office-pack-chat-verify',
      title: '对话验收',
      description:
        '回到对话页，可尝试发送「读取这个 CSV 文件」等指令；Planner 应能看到并调用刚安装的办公员工工具。',
      routeName: 'chat',
      targetSelector: '[data-tour="chat-input-area"]',
      highlightSelector: '[data-tour="chat-input-area"]',
      actionType: 'observe',
      track: 'advanced',
    }),
  ]
}
