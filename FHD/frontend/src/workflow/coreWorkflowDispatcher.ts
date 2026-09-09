import type { CoreWorkflowEmployeeId } from '@/constants/coreWorkflowMod'
import { printApi } from '@/api/print'
import { tryPostCoreWorkflowEmployeeRun } from '@/utils/coreWorkflowEmployeeApi'
import type { CoreWorkflowAuditLine, CoreWorkflowLabelLine } from '@/workflow/coreWorkflowTypes'

export const CORE_WORKFLOW_HOST_EVENTS = {
  labelPrintSignal: 'xcagi:workflow-label-print-signal',
  receiptFeedbackSignal: 'xcagi:workflow-receipt-feedback-signal',
  wechatEnqueue: 'xcagi:wechat-ai-task-enqueue',
  wechatStarPolled: 'xcagi:wechat-star-feed-polled',
} as const

export type CoreWorkflowModRunAction = 'status' | 'signal_ack' | 'audit_summary' | 'feedback_ack' | 'enqueue_ack'

/** Mod 已安装时向员工 run 端点投递；失败不阻断宿主事件链 */
export function dispatchCoreWorkflowModRun(
  modInstalled: boolean,
  employeeId: CoreWorkflowEmployeeId,
  payload: Record<string, unknown>,
): void {
  if (!modInstalled) return
  void tryPostCoreWorkflowEmployeeRun(employeeId, payload)
}

export type LabelPrintSignalDetail = {
  at?: number
  line?: string
  model_number?: string
  modelNumber?: string
  quantity?: number
  contactName?: string
  product_id?: number
  template_id?: string
  paper_width_mm?: number
  paper_height_mm?: number
  jobId?: string
}

export type ReceiptFeedbackSignalDetail = {
  at?: number
  line?: string
  contactName?: string
  messageText?: string
  intentLabel?: string
  intentDetail?: string
}

export type WechatStarPolledDetail = {
  at?: number
  intervalMs?: number
  contactCount?: number
  ok?: boolean
}

export function buildLabelPrintHostUpdate(detail: LabelPrintSignalDetail): {
  lastLabelPrint: CoreWorkflowLabelLine
} {
  const line = String(detail.line || '').trim() || '标签/打印类消息'
  const jobId = typeof detail.jobId === 'string' && /^[a-f0-9]{32}$/.test(detail.jobId) ? detail.jobId : undefined
  return { lastLabelPrint: { at: Number(detail.at) || Date.now(), line, ...(jobId ? { jobId } : {}) } }
}

export function buildReceiptFeedbackHostUpdate(detail: ReceiptFeedbackSignalDetail): {
  lastReceiptFeedback: CoreWorkflowAuditLine
  pushTitle: string
  pushDescription: string
} {
  const contact = String(detail.contactName || '星标联系人').trim()
  const msg = String(detail.messageText || '')
    .trim()
    .slice(0, 400)
  const il = String(detail.intentLabel || '').trim()
  const idetail = String(detail.intentDetail || '')
    .trim()
    .slice(0, 240)
  const line = String(detail.line || '').trim() || `${contact}：${msg.slice(0, 80)}`
  const detailParts = [
    `【客户反馈 · 业务进程】联系人：${contact}`,
    il ? `预处理意图：${il}` : '',
    idetail ? `说明：${idetail}` : '',
    msg ? `原文摘要：${msg}` : '',
  ].filter(Boolean)
  return {
    lastReceiptFeedback: {
      at: Number(detail.at) || Date.now(),
      line,
      detail: detailParts.join('\n'),
    },
    pushTitle: '收货确认 · 客户业务进程',
    pushDescription: line.length > 100 ? `${line.slice(0, 100)}…` : line,
  }
}

export function buildWechatMonitorUpdate(detail: WechatStarPolledDetail): {
  monitor: {
    lastPolledAt: number
    pollIntervalMs: number
    starredContactCount?: number
    pollOk?: boolean
  }
} {
  return {
    monitor: {
      lastPolledAt: Number(detail.at) || Date.now(),
      pollIntervalMs: Number(detail.intervalMs) || 60000,
      starredContactCount: typeof detail.contactCount === 'number' ? detail.contactCount : undefined,
      pollOk: detail.ok !== false,
    },
  }
}

export async function runLabelPrintSideEffect(detail: LabelPrintSignalDetail): Promise<{
  status: 'needs_configuration' | 'generated' | 'failed'
  message: string
  jobId?: string
}> {
  const { product_id, template_id, paper_width_mm, paper_height_mm } = detail
  const copies = detail.quantity ?? 1
  if (!Number.isInteger(product_id) || Number(product_id) <= 0 || typeof template_id !== 'string' || !template_id.trim()
    || !Number.isInteger(copies) || copies < 1 || copies > 100
    || !Number.isFinite(paper_width_mm) || Number(paper_width_mm) < 10 || Number(paper_width_mm) > 500
    || !Number.isFinite(paper_height_mm) || Number(paper_height_mm) < 10 || Number(paper_height_mm) > 500) {
    return { status: 'needs_configuration', message: '请在标签打印页选择具体产品和模板，核对张数与纸张尺寸后生成预览；当前未提交打印。' }
  }
  try {
    const res = await printApi.printSingleLabel({ product_id, template_id, copies, paper_width_mm, paper_height_mm })
    if (!res?.success || !res.job?.id || res.job.status !== 'generated') {
      return { status: 'failed', message: res?.message || '标签预览未生成，请检查配置后重试。' }
    }
    return { status: 'generated', jobId: res.job.id, message: `标签预览已生成（任务 ${res.job.id}），请预览并确认后提交打印。` }
  } catch (err) {
    return { status: 'failed', message: err instanceof Error ? err.message : '标签预览生成失败，请重试。' }
  }
}
