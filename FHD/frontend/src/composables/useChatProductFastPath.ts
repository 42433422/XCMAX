/** 产品关键词快路径（跳过完整 Planner，直接查产品库）。 */
import productsApi from '@/api/products'
import type { ChatPlannerPayload } from '@/types/chat'
import { asRecord } from '@/utils/typeGuards'

export type ChatProductFastPathDeps = {
  addAndSaveMessage: (content: string, role: 'ai') => Promise<void>
  syncTaskFromChatResponse: (payload: ChatPlannerPayload, userText: string) => void
  attachContextSummaryToLastAiMessage: () => void
  attachThinkingStepsToLastAiMessage: (data: ChatPlannerPayload) => void
  attachTodoStepsToLastAiMessage: (data: ChatPlannerPayload) => void
  attachWorkflowTraceToLastAiMessage: (data: ChatPlannerPayload) => void
  handleAutoAction: (action: Record<string, unknown>, userMessage: string) => void
  clearCurrentTask: () => void
}

export async function runProductKeywordFastPath(
  kw: string,
  primaryText: string,
  deps: ChatProductFastPathDeps,
): Promise<boolean> {
  try {
    const resp = await productsApi.searchProducts(kw)
    if (resp && resp.success === false) {
      throw new Error(String(resp.message || '产品库查询失败'))
    }
    const raw =
      resp.data ??
      (resp as unknown as Record<string, unknown>).products ??
      (resp as unknown as Record<string, unknown>).items
    const rows = Array.isArray(raw) ? (raw as Record<string, unknown>[]) : []
    const lines = rows.slice(0, 3).map((row) => {
      const m = String(row.model_number || '').trim()
      const n = String(row.name || row.product_name || '-').trim()
      const p = Number(row.price || 0)
      const pf = Number.isFinite(p) ? p.toFixed(2) : '0.00'
      return `- ${m || '-'} / ${n} / ￥${pf}`
    })
    const previewSuffix = lines.length ? `\n预览命中 ${rows.length} 条：\n${lines.join('\n')}` : ''
    const hasResults = lines.length > 0
    const responseText = hasResults
      ? `已帮你打开产品副窗并带入「${kw}」。可在卡片中查看与修改。${previewSuffix}`
      : `未在产品库中找到「${kw}」，请确认型号或关键词后重试。`
    const payload: ChatPlannerPayload = {
      success: true,
      response: responseText,
      ...(hasResults ? { autoAction: { type: 'show_products_float', query: kw } } : {}),
    }
    const mappedRows = rows.slice(0, 20).map((r) => ({
      id: r.id,
      model_number: r.model_number || '',
      name: r.name || r.product_name || '',
      price: Number(r.price || 0),
      unit: r.unit || '',
    }))
    const totalFromApi = typeof resp.total === 'number' ? resp.total : rows.length
    await deps.addAndSaveMessage(String(payload.response || ''), 'ai')
    deps.syncTaskFromChatResponse(payload, primaryText)
    deps.attachContextSummaryToLastAiMessage()
    deps.attachThinkingStepsToLastAiMessage(payload)
    deps.attachTodoStepsToLastAiMessage(payload)
    deps.attachWorkflowTraceToLastAiMessage(payload)
    if (!payload.task) deps.clearCurrentTask()
    if (payload.autoAction) {
      deps.handleAutoAction(
        {
          ...payload.autoAction,
          hydrateProductSearch: { rows: mappedRows, total: totalFromApi },
        },
        primaryText,
      )
    }
    return true
  } catch {
    return false
  }
}
