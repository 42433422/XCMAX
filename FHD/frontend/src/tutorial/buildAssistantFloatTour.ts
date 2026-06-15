import type { TutorialStep } from './types'
import { createStep } from './stepFactory'

/** 智能对话页：顶栏「副窗」开关与小面板概览 */
export function buildAssistantFloatSteps(): TutorialStep[] {
  return [
    createStep({
      id: 'page-chat-assistant-toggle',
      title: '智能对话 · 打开副窗',
      description:
        '右上角这个「副窗」随时能点开：推送通知、协助查资料、托管开关、新手教程都在里面。点一下打开试试。',
      targetSelector: '[data-tour="assistant-float-toggle"]',
      highlightSelector: '[data-tour="assistant-float-toggle"]',
      actionType: 'click',
      routeName: 'chat',
      allowCardNext: true,
      excludeInPro: false,
    }),
    createStep({
      id: 'page-chat-assistant-panel',
      title: '智能对话 · 副窗分区',
      description: '顶上这一排标签切换不同功能；推送、协助、托管、教程入口都在这儿。',
      targetSelector: '[data-tutorial-spotlight="assistant-panel"]',
      highlightSelector: '[data-tutorial-spotlight="assistant-panel"]',
      actionType: 'observe',
      routeName: 'chat',
      allowCardNext: true,
      excludeInPro: false,
      noAutoSkipWhenMissing: true,
    }),
    createStep({
      id: 'page-chat-assistant-close',
      title: '智能对话 · 收起副窗',
      description: '先把它收起来，后面看侧栏和别的页面才不会挡视线。再点一次「副窗」，或点面板右上角「×」都行。',
      targetSelector: '[data-tour="assistant-float-toggle"]',
      highlightSelector: '[data-tour="assistant-float-close"]',
      actionType: 'click',
      routeName: 'chat',
      allowCardNext: true,
      excludeInPro: false,
    }),
  ]
}
