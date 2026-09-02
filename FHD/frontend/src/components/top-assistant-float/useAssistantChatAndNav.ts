import { nextTick } from 'vue'
import type { Router } from 'vue-router'

const FILL_CHAT_MAX_ATTEMPTS = 4
const FILL_CHAT_RETRY_MS = 80

/**
 * 根据副窗当前展示主题决定跳转到哪个主页面。
 * 若已在目标路由则不重复跳；不能识别主题时 fallback 到聊天页。
 */
const SUBJECT_ROUTE_MAP: Record<string, string> = {
  products: 'products',
  product: 'products',
  customers: 'customers',
  customer: 'customers',
  shipment: 'shipment-records',
  'shipment-records': 'shipment-records',
  template: 'template-preview',
  templates: 'template-preview',
  materials: 'materials',
  inventory: 'inventory',
  approval: 'approval-hub',
}

type RecordOperationFn = (type: string, detail?: Record<string, unknown> | null) => void

/**
 * 聊天输入注入 / 新手对话包跳转 / 主题路由跳转（由 TopAssistantFloat.vue 机械切出，行为不变）。
 */
export function useAssistantChatAndNav(
  {
    router,
    recordOperation,
    closeAssistantPanelUi,
  }: { router: Router; recordOperation: RecordOperationFn; closeAssistantPanelUi: () => void },
) {
  const tryFillChatInput = (text: string | null | undefined) => {
    const t = String(text || '').trim()
    if (!t) return false
    // window.__VUE_CHAT_FILL__ 由聊天页挂载（见 types/global.d.ts），用于向输入框注入文本
    if (typeof window.__VUE_CHAT_FILL__ === 'function') {
      return window.__VUE_CHAT_FILL__(t)
    }
    return false
  }

  const fillChatInputWithRetry = async (text: string | null | undefined) => {
    const t = String(text || '').trim()
    if (!t) return
    for (let i = 0; i < FILL_CHAT_MAX_ATTEMPTS; i += 1) {
      if (i > 0) {
        await new Promise((r) => setTimeout(r, FILL_CHAT_RETRY_MS))
      }
      if (tryFillChatInput(t)) return
    }
  }

  const onStarterPackItemClick = async (text: string | null | undefined) => {
    recordOperation('starter_pack', { text: String(text || '').slice(0, 120) })
    await router.push({ name: 'chat' })
    await nextTick()
    await fillChatInputWithRetry(text)
    // 填入后收起副窗，避免遮挡主对话与右侧「当前任务」预览（发货单等流程主要看任务面板）
    closeAssistantPanelUi()
  }

  const navigateToSubjectPage = async (subject: string | null | undefined) => {
    const routeName = SUBJECT_ROUTE_MAP[String(subject || '').toLowerCase()] || 'chat'
    if (router.currentRoute.value.name !== routeName) {
      await router.push({ name: routeName }).catch(() => {})
    }
  }

  return {
    FILL_CHAT_MAX_ATTEMPTS,
    FILL_CHAT_RETRY_MS,
    tryFillChatInput,
    fillChatInputWithRetry,
    onStarterPackItemClick,
    navigateToSubjectPage,
  }
}
