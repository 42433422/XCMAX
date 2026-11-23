import { requestJson } from '../infrastructure/http/client'

const endpoint = '/api/agent/butler/life'
const portfolios = '/api/xcmax/strategic/portfolios'

export interface XiaoCPortfolioLimits {
  cost_cents: number
  tokens: number
  compute_seconds: number
  max_parallel: number
  max_failures: number
  stop_loss_cents: number
  min_roi_bps: number
  observation_hours: number
  expires_at: string
  tariffs: { provider: string; model: string; input_cents_per_million: number; output_cents_per_million: number; source: string }[]
}

export interface XiaoCPortfolioTemplate {
  decision_id: string
  goal: string
  status: string
  limits: XiaoCPortfolioLimits
  opportunities: {
    employee_id: string
    title: string
    task?: string
    source_refs?: string[]
    input_data?: Record<string, unknown>
    execution_binding?: {
      pack_id: string
      version: string
      manifest_sha256: string
      archive_sha256: string
      config_sha256: string
      input_sha256: string
    }
    cost_cents?: number
    tokens?: number
    compute_seconds?: number
  }[]
  proposal_sha256: string
}

export interface XiaoCLifePolicy {
  daily_token_limit: number
  daily_cycle_limit: number
  exploration_percent: number
  wake_interval_seconds: number
  authorization_expires_at: string | null
  portfolio_limits?: XiaoCPortfolioLimits | null
  employee_id?: string
  task_input?: Record<string, unknown>
  retort_template_id?: string
}

export interface XiaoCLifeEvent {
  id: string
  kind: string
  summary: string
  evidence_refs: string[]
  created_at: string
  model?: string | null
  actual_tokens?: number | null
  status: string
}

export interface XiaoCLifeGoal {
  id: string
  domain: string
  title: string
  description?: string
  status: string
  evidence_refs: string[]
  decision_id?: number | string | null
  retort_request_id?: string
}

export interface XiaoCLifeState {
  identity_id: string
  scope: 'enterprise'
  owner_user_id?: number | null
  revision: number
  level: number
  paused: boolean
  status: string
  mission: string
  activity: { summary?: string; title?: string; status?: string; model?: string } | null
  goals: XiaoCLifeGoal[]
  interests: { topic: string; confidence: number; evidence_refs: string[] }[]
  self_model: Record<string, unknown>
  events: XiaoCLifeEvent[]
  budget: {
    date?: string
    timezone?: string
    used_tokens: number
    reserved_tokens: number
    cycles: number
    exploration_tokens: number
  }
  policy: XiaoCLifePolicy
  blockers: string[]
  updated_at: string
  next_wake_at: string | null
}

export interface XiaoCLifeChange {
  level?: number
  paused?: boolean
  mission?: string
  policy?: XiaoCLifePolicy
}

export const xiaocLifeApi = {
  read: () => requestJson<XiaoCLifeState>(endpoint),
  update: (expectedRevision: number, change: XiaoCLifeChange) =>
    requestJson<XiaoCLifeState>(endpoint, {
      method: 'PUT',
      body: JSON.stringify({ expected_revision: expectedRevision, ...change }),
    }),
  templates: () => requestJson<{ items: XiaoCPortfolioTemplate[] }>(portfolios),
  portfolio: (id: string) => requestJson<XiaoCPortfolioTemplate>(`${portfolios}/${encodeURIComponent(id)}`),
  approvePortfolio: (id: string, proposalSha256: string) =>
    requestJson<{ decision_id: string; status: string }>(`${portfolios}/${encodeURIComponent(id)}/approve`, {
      method: 'POST',
      body: JSON.stringify({ expected_proposal_sha256: proposalSha256, review_notes: '管理端小 C 目标页人工审核' }),
    }),
  promote: (
    goalId: string,
    expectedRevision: number,
    employeeId: string,
    limits: XiaoCPortfolioLimits,
    inputData: Record<string, unknown>,
  ) =>
    requestJson<{ decision_id: string; life: XiaoCLifeState }>(`${endpoint}/goals/${encodeURIComponent(goalId)}/portfolio`, {
      method: 'POST',
      body: JSON.stringify({ expected_revision: expectedRevision, employee_id: employeeId, limits, input_data: inputData }),
    }),
}

export const xiaocLevelLabels: Readonly<Record<number, string>> = {
  1: '对话助手',
  2: '智能执行',
  3: '自主任务',
  4: '自治运营',
  5: '自主成长',
  6: '数字生命',
}

export function xiaocStateLabel(status: string): string {
  const labels: Record<string, string> = {
    idle: '等待新事件',
    waiting: '等待新事件',
    sleeping: '等待唤醒',
    paused: '自主活动已暂停',
    blocked: '等待运行条件',
    thinking: '正在规划',
    running: '正在执行',
    acting: '正在执行',
    reflecting: '正在复盘',
    failed: '本轮失败',
    error: '本轮失败',
    completed: '已完成',
    awaiting_engineering_budget: '等待公司工程预算',
    evolution_delivery_verified: '改进发布已核验',
    evolution_evidence_incomplete: '改进证据待核对',
    evolution_failed: '改进未通过',
    waiting_recovery: '等待恢复核验',
    awaiting_dispatch_approval: '等待改进派工审批',
    awaiting_acceptance: '等待独立验收审批',
    waiting_execution: '等待原工程执行',
    waiting_delivery: '等待正式发布',
    verified: '已核验',
    proposed: '已提出',
    pending: '待处理',
    planned: '已规划',
    active: '进行中',
    queued: '已排队',
    waiting_approval: '待审批',
    cancelled: '已取消',
    awaiting_approval: '待审批',
    approved: '已批准，等待执行回执',
    applied: '设置已生效',
    hypothesis: '待核验评估',
    policy_changed: '运行模式已变化',
    unknown: '状态待核实（unknown）',
    waiting_feedback: '等待反馈',
    rejected: '未获批准',
    recorded: '已记录',
  }
  return labels[status] ?? (status ? `状态待核实（${status}）` : '状态待核实')
}
