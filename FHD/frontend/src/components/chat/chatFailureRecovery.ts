import type { UiChatMessage } from '@/types/chat-ui'
import { asRecord } from '@/utils/typeGuards'

export type ChatExecutionRecord = NonNullable<UiChatMessage['execution']>

export function readChatExecution(payload: unknown): ChatExecutionRecord | undefined {
  const row = asRecord(payload)
  const data = asRecord(row.data)
  const nested = asRecord(data.data)
  const raw = asRecord(row.execution || data.execution || nested.execution)
  if (typeof raw.committed !== 'boolean') {
    // 模型/规划阶段就失败时，后端会明确标记尚未开始执行：本回合没有任何业务写入。
    const started = row.execution_started ?? data.execution_started ?? nested.execution_started
    if (started === false) {
      return { idempotencyKey: '', intent: '', committed: false, effect: 'none' }
    }
    return undefined
  }
  const effect = String(raw.effect || 'none')
  return {
    idempotencyKey: String(raw.idempotency_key || raw.idempotencyKey || ''),
    intent: String(raw.intent || ''),
    committed: raw.committed,
    effect,
    tenantId: String(raw.tenant_id || raw.tenantId || ''),
    customerCount: typeof raw.customer_count === 'number' ? raw.customer_count : typeof raw.customerCount === 'number' ? raw.customerCount : null,
    productCount: typeof raw.product_count === 'number' ? raw.product_count : typeof raw.productCount === 'number' ? raw.productCount : null,
  }
}

/** Do not claim a write survived unless an execution record shows it committed. */
export function chatFailureRecoveryText(execution?: { committed?: boolean; effect?: string } | null): string {
  if (execution?.committed === true) {
    return '请先核对上方错误和任务状态。重试只会重新请求模型，已提交的业务操作不会再次执行，也不会撤销。'
  }
  if (execution?.effect === 'preview' || execution?.effect === 'none') return '本轮尚未提交写入，重试只会重新请求模型。'
  return '原任务的写入状态未确认，请先核对业务结果，不要重复提交。'
}

export function modelOutcomeFromText(text: string): 'healthy' | 'degraded' | 'ignore' {
  const plain = text.trim()
  if (!plain) return 'ignore'
  if (/模型未返回可显示|请求超时|模型服务暂时|对话连接已超时|流式对话失败|处理失败|本轮回复已结束，但没有收到正文/.test(plain)) {
    return 'degraded'
  }
  return 'healthy'
}
