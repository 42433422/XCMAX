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
      return { idempotencyKey: '', intent: '', committed: false, effect: 'none', outcome: 'not_executed' }
    }
    return undefined
  }
  const effect = String(raw.effect || 'none')
  return {
    idempotencyKey: String(raw.idempotency_key || raw.idempotencyKey || ''),
    intent: String(raw.intent || ''),
    committed: raw.committed,
    effect,
    outcome: String(raw.outcome || ''),
    tenantId: String(raw.tenant_id || raw.tenantId || ''),
    customerCount: typeof raw.customer_count === 'number' ? raw.customer_count : typeof raw.customerCount === 'number' ? raw.customerCount : null,
    productCount: typeof raw.product_count === 'number' ? raw.product_count : typeof raw.productCount === 'number' ? raw.productCount : null,
  }
}

export type ChatExecutionOutcome = 'not_executed' | 'partial' | 'unknown' | 'succeeded'

type ChatExecutionLike = { committed?: boolean; effect?: string; outcome?: string } | null | undefined

/**
 * 失败语义三档：未执行 / 已执行结果未知 / 部分成功。
 * 优先采用后端显式 outcome，再按 committed + effect 推导。
 */
export function chatExecutionOutcome(execution: ChatExecutionLike): ChatExecutionOutcome {
  const raw = String(execution?.outcome || '').toLowerCase()
  if (raw === 'not_executed' || raw === 'none') return 'not_executed'
  if (raw === 'partial') return 'partial'
  if (raw === 'unknown') return 'unknown'
  if (execution?.effect === 'partial') return 'partial'
  if (execution?.committed === true) return 'succeeded'
  if (execution?.committed === false || execution?.effect === 'none' || execution?.effect === 'preview') return 'not_executed'
  return 'unknown'
}

/** 不要笼统说「写入状态未确认」：未执行、部分成功、结果未知要给出不同指引。 */
export function chatFailureRecoveryText(execution?: ChatExecutionLike): string {
  switch (chatExecutionOutcome(execution)) {
    case 'not_executed':
      return '本轮未提交写入，重试只会重新请求模型。'
    case 'partial':
      return '部分步骤已写入、部分未完成。请先核对下方结果，勿整轮重复提交。'
    case 'succeeded':
      return '请先核对上方错误和任务状态。重试只会重新请求模型，已提交的业务操作不会再次执行，也不会撤销。'
    default:
      return '已执行但结果未知，请先核对业务结果，不要重复提交。'
  }
}

export function modelOutcomeFromText(text: string): 'healthy' | 'degraded' | 'ignore' {
  const plain = text.trim()
  if (!plain) return 'ignore'
  if (/模型未返回可显示|请求超时|模型服务暂时|对话连接已超时|流式对话失败|处理失败|本轮回复已结束，但没有收到正文/.test(plain)) {
    return 'degraded'
  }
  return 'healthy'
}
