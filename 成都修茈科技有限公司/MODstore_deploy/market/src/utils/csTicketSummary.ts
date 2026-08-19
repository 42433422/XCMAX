import {
  shortTicketRef,
  ticketIntentLabel,
  ticketLifecycleLabel,
} from './csTicketLifecycle'
import { asUnknownRecord, type UnknownRecord } from './typeNarrowing'

function humanizeRationale(raw: unknown): string {
  let s = String(raw || '').trim()
  if (!s) return ''
  const map: Record<string, string> = {
    order_no: '订单号',
    catalog_id: '商品编号',
    complaint_type: '问题类型',
    reason: '原因说明',
    provider: '模型厂商',
    model: '模型名称',
  }
  for (const [k, v] of Object.entries(map)) s = s.split(k).join(v)
  // 旧版内部话术 → 白话
  if (/审核标准|低风险动作|自动受理/.test(s)) {
    return ''
  }
  if (/合规审核队列|写入审计/.test(s)) {
    return '已进入审核，结果会尽快告诉你。'
  }
  return s
}

function actionLine(actions: unknown[]): {
  ok: boolean
  failed: boolean
  labels: string[]
  onlyEmployeeFollowup: boolean
} {
  const map: Record<string, string> = {
    'refund.apply': '退款申请',
    'catalog.complaint.create': '投诉登记',
    'catalog.compliance.review': '合规审核',
    'llm.model_capability.propose': '模型扩展申请',
    'employee.dispatch': '员工跟进',
  }
  const labels: string[] = []
  let failed = false
  let hasBusinessDone = false
  let hasEmployeeFollowup = false
  for (const value of actions || []) {
    const item = asUnknownRecord(value)
    const type = String(item.action_type || '')
    const name = map[type] || ''
    const st = String(item?.status || '').toLowerCase()
    if (!name) continue
    // 员工跟进是进度信号，不算「已办妥」，失败也不对用户报红
    if (type === 'employee.dispatch') {
      hasEmployeeFollowup = true
      if (!labels.includes(name)) labels.push(name)
      continue
    }
    if (st === 'completed' || st === 'skipped') {
      hasBusinessDone = true
      if (!labels.includes(name)) labels.push(name)
    } else if (st === 'failed') {
      failed = true
      if (!labels.includes(name)) labels.push(name)
    }
  }
  return {
    ok: hasBusinessDone,
    failed,
    labels,
    onlyEmployeeFollowup: hasEmployeeFollowup && !hasBusinessDone && !failed,
  }
}

/** 把工单详情收成用户看得懂的一段话（对话里不再堆多张卡） */
export function composeTicketUserMessage(input: {
  ticket: UnknownRecord
  decision?: UnknownRecord | null
  actions?: unknown[]
}): string {
  const ticket = input.ticket || {}
  const decision = input.decision || null
  const actions = Array.isArray(input.actions) ? input.actions : []
  const kind = ticketIntentLabel(ticket.intent)
  const stage = ticketLifecycleLabel({
    ...ticket,
    decision_status: ticket.decision_status || decision?.decision,
  })
  const ref = shortTicketRef(ticket)
  const subject = String(ticket.subject_id || '').trim()
  const head = subject ? `你的${kind}（${ref}）` : `你的${kind}`
  const act = actionLine(actions)
  const rationale = humanizeRationale(decision?.rationale)
  const decisionKey = String(decision?.decision || ticket.decision_status || '').toLowerCase()

  if (stage === '待补充' || decisionKey === 'needs_more_info') {
    const need = rationale || '还需要补充一些信息。'
    return `${head}：还差材料。${need}请直接在下方发送补充内容。`
  }

  if (act.failed) {
    return (
      `${head}：处理没有成功` +
      (act.labels.length ? `（${act.labels.join('、')}）` : '') +
      '。常见原因是订单号无效或状态不支持。请发真实订单号后再试，或说「提交工单」。'
    )
  }

  if (act.ok) {
    return `${head}：已办妥${act.labels.length ? `（${act.labels.join('、')}）` : ''}。如还有问题继续说就行。`
  }

  if (stage === '已完成') {
    return `${head}：已处理完成。`
  }
  if (stage === '有结果' || act.onlyEmployeeFollowup) {
    return `${head}：已有处理进展，值班员工仍在跟进。可继续补充截图或具体页面。`
  }
  if (decisionKey === 'accepted' || stage === '处理中' || stage === '已收到') {
    const tip = rationale && !/自动受理|审核标准/.test(rationale)
      ? rationale
      : '可继续补充截图或页面位置。'
    return `${head}：已收到，正在跟进处理。${tip}`
  }
  return `${head}：当前进度「${stage}」。`
}

export function toUserFacingCards<T>(_cards: T[]): T[] {
  // 对话气泡不再展示多张内部卡
  return []
}
