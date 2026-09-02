import { computed } from 'vue'
import { ApiError } from '@/api'
import productsApi from '@/api/products'
import type { useIndustryUiText } from '@/composables/useIndustryUiText'
import type { AssistantFloatState, AssistantProductRow } from './useAssistantFloatState'

const PRODUCT_SEARCH_TIMEOUT_MS = 30000

type IndustryUiText = ReturnType<typeof useIndustryUiText>

type RecordOperationFn = (type: string, detail?: Record<string, unknown> | null) => void

/** 检索响应的宽松视图：后端可能返回 data / products / items 任一字段 */
interface ProductSearchResponseView {
  success?: boolean
  message?: string
  total?: number
  data?: unknown
  products?: unknown
  items?: unknown
}

/**
 * 产品检索 / 保存 / 空态文案（由 TopAssistantFloat.vue 机械切出，行为不变）。
 */
export function useAssistantProductSearch(
  state: AssistantFloatState,
  { uiText, recordOperation }: { uiText: IndustryUiText; recordOperation: RecordOperationFn },
) {
  const {
    productKeyword,
    productRows,
    loadingProducts,
    lastProductSearchQuery,
    productSearchFailed,
    productSearchErrorText,
    lastProductSearchTotal,
    savingProductId,
  } = state

  /** 产品副窗查询并发序号；仅最后一次请求可结束 loading */
  let productSearchSeq = 0

  const searchProducts = async () => {
    const kw = String(productKeyword.value || '').trim()
    if (!kw) {
      productRows.value = []
      lastProductSearchQuery.value = ''
      lastProductSearchTotal.value = null
      productSearchFailed.value = false
      productSearchErrorText.value = ''
      loadingProducts.value = false
      return
    }
    const seq = ++productSearchSeq
    loadingProducts.value = true
    productSearchFailed.value = false
    productSearchErrorText.value = ''
    const timeoutPromise = new Promise((_, reject) => {
      setTimeout(() => reject(new Error(`请求超时（${PRODUCT_SEARCH_TIMEOUT_MS / 1000} 秒），请检查后端是否卡住或未启动`)), PRODUCT_SEARCH_TIMEOUT_MS)
    })
    try {
      const resp = (await Promise.race([productsApi.searchProducts(kw), timeoutPromise])) as ProductSearchResponseView
      if (seq !== productSearchSeq) return
      if (resp && resp.success === false) {
        productRows.value = []
        lastProductSearchQuery.value = kw
        lastProductSearchTotal.value = 0
        productSearchFailed.value = true
        productSearchErrorText.value = String(resp?.message || `${uiText.entityName.value}库查询失败`)
        return
      }
      const raw = resp?.data ?? resp?.products ?? resp?.items
      const rows = Array.isArray(raw) ? raw : []
      const totalFromApi = typeof resp?.total === 'number' ? resp.total : rows.length
      lastProductSearchTotal.value = totalFromApi
      productRows.value = rows.slice(0, 20).map((r) => ({
        id: r.id,
        model_number: r.model_number || '',
        name: r.name || r.product_name || '',
        price: Number(r.price || 0),
        unit: r.unit || '',
      }))
      recordOperation('search_products', { keyword: kw, hasResult: rows.length > 0, total: totalFromApi })
      lastProductSearchQuery.value = kw
    } catch (e) {
      if (seq !== productSearchSeq) return
      productRows.value = []
      lastProductSearchQuery.value = kw
      lastProductSearchTotal.value = null
      productSearchFailed.value = true
      if (e instanceof ApiError) {
        const st = e.status ? `HTTP ${e.status}` : ''
        productSearchErrorText.value = [st, e.message].filter(Boolean).join(' · ')
      } else {
        const msg = (e as { message?: unknown } | null | undefined)?.message
        productSearchErrorText.value = msg ? String(msg) : '网络异常'
      }
      recordOperation('search_products', { keyword: kw, hasResult: false, failed: true })
    } finally {
      if (seq === productSearchSeq) {
        loadingProducts.value = false
      }
    }
  }

  const productEmptyMessage = computed(() => {
    const cur = String(productKeyword.value || '').trim()
    if (productSearchFailed.value) {
      const detail = productSearchErrorText.value ? `（${productSearchErrorText.value}）` : ''
      return `${uiText.searchFailedMessage.value}${detail}`
    }
    if (!lastProductSearchQuery.value) {
      return uiText.emptyBeforeSearch.value
    }
    if (cur && cur !== lastProductSearchQuery.value) {
      return uiText.keywordChanged.value
    }
    const kw = lastProductSearchQuery.value
    const n = lastProductSearchTotal.value
    const totalHint = typeof n === 'number' ? `${uiText.entityName.value}库中本次条件共 ${n} 条。` : ''
    return `未找到与「${kw}」匹配的${uiText.entityName.value}。${totalHint}可缩短关键词、只输入${uiText.modelLabel.value}，或到左侧「${uiText.entityListName.value}」浏览全库核对${uiText.nameLabel.value}/${uiText.modelLabel.value}。`
  })

  const saveProductRow = async (row: AssistantProductRow) => {
    if (!row?.id) return
    savingProductId.value = row.id
    try {
      await productsApi.updateProduct(row.id, {
        model_number: row.model_number || '',
        name: row.name || '',
        price: Number(row.price || 0),
        unit: row.unit || '',
      })
      recordOperation('save_product', {
        id: row.id,
        name: row.name || '',
        model: row.model_number || '',
      })
    } finally {
      savingProductId.value = null
    }
  }

  return {
    PRODUCT_SEARCH_TIMEOUT_MS,
    searchProducts,
    productEmptyMessage,
    saveProductRow,
  }
}
