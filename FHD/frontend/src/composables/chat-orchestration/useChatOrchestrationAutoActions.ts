/**
 * useChatOrchestration 拆出的副窗推送 / AutoAction 行为（行为零变更）。
 */
import { ref, type Ref } from 'vue'
import type { useTutorialStore } from '@/stores/tutorial'
import { asRecord } from '@/utils/typeGuards'
import { asAutoAction, asShipmentTask, getXcagiWindow } from './chatOrchestrationShared'

export interface ChatOrchestrationAutoActionsDeps {
  latestAssistantPush: Ref<{ title: string; description: string } | null>
  tutorialStore: ReturnType<typeof useTutorialStore>
}

export function useChatOrchestrationAutoActions(deps: ChatOrchestrationAutoActionsDeps) {
  const { latestAssistantPush, tutorialStore } = deps
  const pushCopied = ref(false)

  function emitAssistantPush(payload: unknown = {}) {
    const row = asRecord(payload)
    const detail = {
      title: String(row.title || '任务推送').trim(),
      description: String(row.description || '').trim(),
      feature: row.feature || '',
      query: row.query || '',
    }
    latestAssistantPush.value = detail
    window.dispatchEvent(new CustomEvent('xcagi:assistant-push', { detail }))
  }

  /** 待确认的发货单生成任务出现时收起顶部副窗，突出右侧「当前任务」面板；若同时需打开产品副窗则不收起 */
  function maybeCloseAssistantFloatForShipmentTask(task: unknown, autoAction: unknown) {
    // 教程步骤若声明了 assistantTab，需要副窗保持打开以定位高亮；否则发货任务触发的「收起副窗」会与教程打开副窗竞态，导致点空气。
    if (tutorialStore.isActive && tutorialStore.currentStep?.assistantTab) {
      return
    }
    const row = asShipmentTask(task)
    const action = asAutoAction(autoAction)
    if (!row || row.completed) return
    const toolId = String(row.payload?.tool_id || row.payload?.params?.tool_id || '').trim()
    const isShipment = row.type === 'shipment_generate' || toolId === 'shipment_generate'
    if (!isShipment) return
    const at = String(action.type || '').trim()
    if (at === 'show_products' || at === 'show_products_float') return
    window.dispatchEvent(
      new CustomEvent('xcagi:close-assistant-float', {
        detail: { reason: 'shipment_task_confirm' },
      }),
    )
  }

  function handleAutoAction(action: unknown, userMessage: string = '') {
    const autoAction = asAutoAction(action)
    console.log('[AutoAction] 触发:', autoAction, '| 用户消息:', userMessage)
    const type = String(autoAction.type || '')
    const actionQuery = String(
      Object.prototype.hasOwnProperty.call(autoAction, 'query') ? (autoAction.query ?? '') : autoAction.keyword || userMessage || '',
    ).trim()

    // 产品副窗打开（工作流会下发 show_products_float）
    if (type === 'show_products' || type === 'show_products_float') {
      emitAssistantPush({
        title: '产品查询',
        description: '已在副窗打开产品卡片编辑窗口，可直接查询并修改。',
        feature: 'products',
        query: actionQuery,
      })
      const floatDetail: Record<string, unknown> = {
        feature: 'products',
        query: actionQuery,
        forceOpen: true,
      }
      const hyd = autoAction.hydrateProductSearch
      if (hyd && Array.isArray(hyd.rows)) {
        floatDetail.hydrateProductSearch = { rows: hyd.rows, total: hyd.total }
      }
      window.dispatchEvent(new CustomEvent('xcagi:open-assistant-float', { detail: floatDetail }))
      return
    }

    const viewMap: Record<string, string> = {
      show_chat: 'chat',
      show_products: 'products',
      show_materials: 'materials',
      show_orders: 'orders',
      show_print: 'print',
      show_customers: 'customers',
      show_labels_export: 'print',
    }

    console.log('[AutoAction] 视图映射 type:', type, '-> 目标视图:', viewMap[type] || '未匹配')
    if (viewMap[type]) {
      console.log('[AutoAction] 派发 xcagi:switch-view 事件, detail:', { view: viewMap[type] })
      window.dispatchEvent(new CustomEvent('xcagi:switch-view', { detail: { view: viewMap[type] } }))
      if (viewMap[type] === 'products') {
        emitAssistantPush({
          title: '产品查询',
          description: '可在顶部副窗中直接查询并修改产品信息。',
          feature: 'products',
          query: userMessage || '',
        })
        window.dispatchEvent(
          new CustomEvent('xcagi:open-assistant-float', {
            detail: { feature: 'products', query: userMessage || '' },
          }),
        )
      }
    }
    const event = new CustomEvent('auto-action', { detail: { action: autoAction, userMessage } })
    window.dispatchEvent(event)

    const legacyAutoActionHandler = getXcagiWindow().legacyAutoActionHandler
    if (typeof legacyAutoActionHandler === 'function') {
      legacyAutoActionHandler(autoAction, userMessage)
    }
  }

  async function copyAssistantPushContent() {
    const title = String(latestAssistantPush.value?.title || '').trim()
    const desc = String(latestAssistantPush.value?.description || '').trim()
    const text = [title, desc].filter(Boolean).join('\n')
    if (!text) return
    try {
      pushCopied.value = true
      window.setTimeout(() => {
        pushCopied.value = false
      }, 1200)
    } catch (_e) {
      pushCopied.value = false
    }
  }

  function openAssistantFloatFromTaskPanel() {
    const detail = latestAssistantPush.value || {}
    window.dispatchEvent(new CustomEvent('xcagi:open-assistant-float', { detail }))
  }

  return {
    pushCopied,
    emitAssistantPush,
    maybeCloseAssistantFloatForShipmentTask,
    handleAutoAction,
    copyAssistantPushContent,
    openAssistantFloatFromTaskPanel,
  }
}
