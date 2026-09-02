import type { useTutorialStore } from '@/stores/tutorial'
import type { AssistantFloatState } from './useAssistantFloatState'

type TutorialStore = ReturnType<typeof useTutorialStore>

type RecordOperationFn = (type: string, detail?: Record<string, unknown> | null) => void

/**
 * window 自定义事件处理器（由 TopAssistantFloat.vue 机械切出，行为不变）：
 * 推送 / 打开副窗 / 关闭副窗 / 教程恢复与设置标签页。
 */
export function useAssistantFloatEvents(
  state: AssistantFloatState,
  {
    tutorialStore,
    recordOperation,
    searchProducts,
    focusToggleAfterClose,
    addPush,
  }: {
    tutorialStore: TutorialStore
    recordOperation: RecordOperationFn
    searchProducts: () => Promise<void>
    focusToggleAfterClose: () => void
    addPush: (detail: { title?: string; description?: string } | null | undefined) => void
  },
) {
  const {
    isOpen,
    activeTab,
    showAdvancedCourses,
    pushFeed,
    popupNotice,
    hasUnreadPush,
    operationHistory,
    productKeyword,
    productRows,
    linkedSheetName,
    linkedSheetIndex,
    linkedGridData,
    linkedSheetFields,
    linkedSheetSampleRows,
    topScrollInnerWidth,
    loadingProducts,
    lastProductSearchQuery,
    productSearchFailed,
    productSearchErrorText,
    lastProductSearchTotal,
  } = state

  const onAssistantPush = (evt: CustomEvent) => {
    const detail = evt?.detail || {}
    addPush(detail)
  }

  const onOpenAssistantFloat = (evt: CustomEvent) => {
    const detail = evt?.detail || {}
    recordOperation('open_float_event', { feature: detail?.feature || '' })
    const feature = String(detail?.feature || '').trim().toLowerCase()
    const shouldAutoOpen = !!(
      detail?.forceOpen ||
      detail?.task ||
      ['products', 'assistant', 'print', 'shipment', 'shipment_generate', 'tutorial'].includes(feature)
    )
    if (shouldAutoOpen) {
      isOpen.value = true
    } else {
      hasUnreadPush.value = true
    }
    if (detail?.feature === 'products' || detail?.feature === 'assistant') {
      activeTab.value = 'assistant'
      const hyd = detail?.hydrateProductSearch
      if (hyd && Array.isArray(hyd.rows)) {
        const q = String(detail.query || '').trim()
        productKeyword.value = q
        productRows.value = hyd.rows
        lastProductSearchQuery.value = q
        lastProductSearchTotal.value = typeof hyd.total === 'number' ? hyd.total : hyd.rows.length
        loadingProducts.value = false
        productSearchFailed.value = false
        productSearchErrorText.value = ''
        recordOperation('search_products', {
          keyword: q,
          hasResult: hyd.rows.length > 0,
          total: lastProductSearchTotal.value,
          hydrated: true,
        })
      } else if (detail?.query) {
        const q = String(detail.query).trim()
        const sameKw = q && q === String(productKeyword.value || '').trim()
        if (!sameKw) {
          productKeyword.value = q
          searchProducts()
        } else if (!loadingProducts.value && productRows.value.length === 0) {
          searchProducts()
        }
      }
    } else if (detail?.feature === 'starterPack') {
      activeTab.value = 'starterPack'
    } else if (detail?.feature === 'tutorial') {
      isOpen.value = true
      activeTab.value = 'tutorial'
      showAdvancedCourses.value = detail?.advanced === true
    } else {
      activeTab.value = 'push'
    }
  }

  const onRestoreFloatState = (evt: CustomEvent) => {
    const detail = evt?.detail || {}
    const snapshot = detail.assistantState || null
    if (snapshot) {
      pushFeed.value = Array.isArray(snapshot.pushFeed) ? [...snapshot.pushFeed] : []
      productKeyword.value = String(snapshot.productKeyword || '')
      productRows.value = Array.isArray(snapshot.productRows) ? [...snapshot.productRows] : []
      linkedSheetName.value = String(snapshot.linkedSheetName || '')
      linkedSheetIndex.value = Number(snapshot.linkedSheetIndex || 0)
      linkedGridData.value = snapshot.linkedGridData || null
      linkedSheetFields.value = Array.isArray(snapshot.linkedSheetFields) ? [...snapshot.linkedSheetFields] : []
      linkedSheetSampleRows.value = Array.isArray(snapshot.linkedSheetSampleRows) ? [...snapshot.linkedSheetSampleRows] : []
      topScrollInnerWidth.value = Number(snapshot.topScrollInnerWidth || 0)
      loadingProducts.value = !!snapshot.loadingProducts
      lastProductSearchQuery.value = String(snapshot.lastProductSearchQuery || '')
      productSearchFailed.value = !!snapshot.productSearchFailed
      productSearchErrorText.value = String(snapshot.productSearchErrorText || '')
      lastProductSearchTotal.value = snapshot.lastProductSearchTotal ?? null
      popupNotice.value = snapshot.popupNotice || null
      hasUnreadPush.value = !!snapshot.hasUnreadPush
      operationHistory.value = Array.isArray(snapshot.operationHistory) ? [...snapshot.operationHistory] : []
    }
    isOpen.value = !!detail.isOpen
    activeTab.value = String(detail.activeTab || 'push')
  }

  const onTutorialSetAssistantTab = (evt: CustomEvent) => {
    const detail = evt?.detail || {}
    if (detail.open) {
      isOpen.value = true
    }
    const tab = String(detail.tab || '').trim()
    if (tab) {
      activeTab.value = tab
    }
  }

  const onCloseAssistantFloat = () => {
    if (tutorialStore.isActive && tutorialStore.currentStep?.assistantTab) {
      return
    }
    recordOperation('close_float_event', { source: 'shipment_task' })
    isOpen.value = false
    focusToggleAfterClose()
  }

  return {
    onAssistantPush,
    onOpenAssistantFloat,
    onRestoreFloatState,
    onTutorialSetAssistantTab,
    onCloseAssistantFloat,
  }
}
