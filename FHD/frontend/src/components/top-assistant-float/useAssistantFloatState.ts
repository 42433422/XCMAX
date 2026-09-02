import { ref } from 'vue'
import type { ComponentPublicInstance } from 'vue'

/** 推送条目 */
export interface AssistantPushItem {
  id: string
  title: string
  description: string
}

/** 操作日志条目 */
export interface AssistantOperationRecord {
  id: string
  type: string
  detail: Record<string, unknown>
  at: number
}

/** 产品检索结果行（副窗内可编辑） */
export interface AssistantProductRow {
  id: number
  model_number: string
  name: string
  price: number
  unit: string
}

/**
 * 副窗全部响应式状态（与原 TopAssistantFloat.vue 逐项对应）。
 * 由入口创建一次，各行为 composable 共享同一组 ref，保证与拆分前同一实例。
 */
export function useAssistantFloatState() {
  // 面板可见性 / 标签页
  const isOpen = ref(false)
  const activeTab = ref('push')
  const showAdvancedCourses = ref(false)
  const floatToggleRef = ref<HTMLElement | null>(null)
  const assistantPanelRef = ref<HTMLElement | null>(null)

  // 推送与操作日志
  const pushFeed = ref<AssistantPushItem[]>([])
  const popupNotice = ref<{ title: string; description: string } | null>(null)
  const hasUnreadPush = ref(false)
  const operationHistory = ref<AssistantOperationRecord[]>([])

  // 产品检索
  const productKeyword = ref('')
  const productRows = ref<AssistantProductRow[]>([])
  const loadingProducts = ref(false)
  /** 最近一次「已完成」的检索关键词（用于区分未搜索 / 已搜无结果 / 改词未搜） */
  const lastProductSearchQuery = ref('')
  const productSearchFailed = ref(false)
  const productSearchErrorText = ref('')
  /** 最近一次成功请求时后端返回的 total（用于无结果时说明） */
  const lastProductSearchTotal = ref<number | null>(null)
  const savingProductId = ref<number | null>(null)

  // 关联 Excel 网格
  const linkedSheetName = ref('')
  const linkedSheetIndex = ref(0)
  const linkedGridData = ref<Record<string, unknown> | null>(null)
  const linkedSheetFields = ref<unknown[]>([])
  const linkedSheetSampleRows = ref<unknown[]>([])
  const topScrollRef = ref<HTMLElement | null>(null)
  const excelPreviewRef = ref<ComponentPublicInstance | null>(null)
  const topScrollInnerWidth = ref(0)

  return {
    isOpen,
    activeTab,
    showAdvancedCourses,
    floatToggleRef,
    assistantPanelRef,
    pushFeed,
    popupNotice,
    hasUnreadPush,
    operationHistory,
    productKeyword,
    productRows,
    loadingProducts,
    lastProductSearchQuery,
    productSearchFailed,
    productSearchErrorText,
    lastProductSearchTotal,
    savingProductId,
    linkedSheetName,
    linkedSheetIndex,
    linkedGridData,
    linkedSheetFields,
    linkedSheetSampleRows,
    topScrollRef,
    excelPreviewRef,
    topScrollInnerWidth,
  }
}

export type AssistantFloatState = ReturnType<typeof useAssistantFloatState>
