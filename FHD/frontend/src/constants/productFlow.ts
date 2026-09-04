/**
 * 可交付宿主标准用户流程（与 docs/guides/PRODUCT_USER_FLOW.md 对齐）
 */

import { ref, type Ref } from 'vue'
import {
  buildTenantScopedStorageKey,
  readTenantScopedStorageItem,
  removeTenantScopedStorageItem,
  resolveTenantStorageScopeFromRuntime,
  writeTenantScopedStorageItem,
} from '@/utils/tenantStorageScope'

export const LS_PRODUCT_FLOW_COMPLETED = 'xcagi_product_flow_completed'
export const LS_PRODUCT_FLOW_HOST_ACK = 'xcagi_product_flow_host_ack'
export const LS_PRODUCT_FLOW_LAST_STEP = 'xcagi_product_flow_last_step'
export const LS_PRODUCT_FLOW_PENDING_PROMPT = 'xcagi_product_flow_pending_prompt'
export const LS_PRODUCT_FLOW_FIRST_TASK_PENDING = 'xcagi_product_flow_first_task_pending'
export const LS_PRODUCT_FLOW_FIRST_TASK_RUN_ID = 'xcagi_product_flow_first_task_run_id'

/** 副窗「新手教程」默认路线 id（宿主三步引导，原基础教程） */
export const DEFAULT_TUTORIAL_TRACK_ID = 'basic'

export function isTutorialReplayQuery(raw: unknown): boolean {
  return (
    String(raw || '')
      .trim()
      .toLowerCase() === 'tutorial'
  )
}

export function readOnboardingReturnPath(raw: unknown): string {
  const p = String(raw || '').trim()
  if (p.startsWith('/')) return p
  return '/'
}

export type ProductFlowStepId = 'welcome' | 'host-pack' | 'industry' | 'seed-demo' | 'first-ai-task' | 'done'

export interface ProductFlowStepMeta {
  id: ProductFlowStepId
  index: number
  title: string
  subtitle: string
}

/** 首次登录完整步骤轨：认识 → 行业 → 菜单 → 演示数据 → AI 第一单。 */
export const PRODUCT_FLOW_STEPS: ProductFlowStepMeta[] = [
  {
    id: 'welcome',
    index: 1,
    title: '认识XC',
    subtitle: '专属于您的数字公司 · 先装 Mod，AI 员工按需再来',
  },
  {
    id: 'industry',
    index: 2,
    title: '行业定型',
    subtitle: '先定行业方向；日常默认只有智能对话与智能生态',
  },
  {
    id: 'host-pack',
    index: 3,
    title: '准备菜单',
    subtitle: '一键装齐本行业侧栏菜单，即可进入对话',
  },
  {
    id: 'seed-demo',
    index: 4,
    title: '演示数据',
    subtitle: '准备一套可删除的演示客户和商品，第一次操作不再面对空白页',
  },
  {
    id: 'first-ai-task',
    index: 5,
    title: 'AI 第一单',
    subtitle: '让 AI 员工串联查询与制单工具，陪您完成第一笔业务',
  },
  {
    id: 'done',
    index: 6,
    title: '开始使用',
    subtitle: '进入智能对话与日常操作',
  },
]

/** 引导「行业定型」当前开放可选（其余仅展示）；运行时以服务器 catalog 为准 */
export const ONBOARDING_OPEN_INDUSTRY_IDS = ['涂料', '考勤'] as const

export type OnboardingOpenIndustryId = (typeof ONBOARDING_OPEN_INDUSTRY_IDS)[number]

let runtimeOpenIndustryIds: readonly string[] | null = null

export function setRuntimeOnboardingOpenIndustryIds(ids: string[] | null | undefined): void {
  runtimeOpenIndustryIds = ids?.length ? ids : null
}

export function readRuntimeOnboardingOpenIndustryIds(): readonly string[] {
  return runtimeOpenIndustryIds ?? ONBOARDING_OPEN_INDUSTRY_IDS
}

export function isOnboardingIndustryOpen(industryId: string): boolean {
  const id = String(industryId || '').trim()
  return readRuntimeOnboardingOpenIndustryIds().includes(id)
}

export function defaultOnboardingIndustryId(): OnboardingOpenIndustryId {
  return '涂料'
}

/** @deprecated 用 industry-baseline API summary；保留作离线兜底 */
export function industryBaselineHint(industryId: string): string {
  const id = String(industryId || '').trim() || '通用'
  const hints: Record<string, string> = {
    通用: '通用场景：工作流员工、Planner 工具、企微与局域网入口等基础线，用到哪补哪即可。',
    涂料: '涂料/批发类：在通用基础线上，出货、客户、标签打印等行业 Mod 可按需从扩展市场安装。',
    批发: '批发分销：基础线装齐后，库存与客户相关 Mod 建议从扩展市场按需加载。',
    考勤: '考勤排班：先补 ERP 门面与表格工具侧栏，再装行业包；部门/人员与 AI 员工在账号定制 Mod。',
    电商: '电商零售：基础线装齐后，订单与 SKU 相关 Mod 可按需安装。',
    餐饮: '餐饮门店：基础线装齐后，食材与订货 Mod 可按需安装。',
    物流: '物流运单：基础线装齐后，运单与客户 Mod 可按需安装。',
  }
  return hints[id] || hints['通用']
}

export function readProductFlowCompleted(): boolean {
  if (typeof localStorage === 'undefined') return true
  try {
    const scope = resolveTenantStorageScopeFromRuntime()
    const scoped = readTenantScopedStorageItem(LS_PRODUCT_FLOW_COMPLETED, scope)
    if (scoped !== null) return scoped === '1'
    return scope === 'local' && localStorage.getItem(LS_PRODUCT_FLOW_COMPLETED) === '1'
  } catch {
    return true
  }
}

export function markProductFlowCompleted(): void {
  if (typeof localStorage === 'undefined') return
  try {
    const scope = resolveTenantStorageScopeFromRuntime()
    writeTenantScopedStorageItem(LS_PRODUCT_FLOW_COMPLETED, '1', scope)
    if (scope === 'local') {
      localStorage.setItem(LS_PRODUCT_FLOW_COMPLETED, '1')
    }
  } catch {
    /* ignore */
  }
  void import('@/utils/workspacePrefsApi')
    .then(({ queueWorkspacePrefsSync }) => {
      queueWorkspacePrefsSync({ product_flow_completed: true })
    })
    .catch(() => {})
}

export function readHostPackAcknowledged(): boolean {
  if (typeof localStorage === 'undefined') return true
  try {
    const scope = resolveTenantStorageScopeFromRuntime()
    const scoped = readTenantScopedStorageItem(LS_PRODUCT_FLOW_HOST_ACK, scope)
    if (scoped !== null) return scoped === '1'
    return scope === 'local' && localStorage.getItem(LS_PRODUCT_FLOW_HOST_ACK) === '1'
  } catch {
    return true
  }
}

/**
 * 响应式「第三步补基础线已确认」标记：供侧栏等在引导完成后即时长出行业菜单，
 * 无需刷新页面。同页 mark 时直接更新；跨标签页经 storage 事件同步。
 */
const hostPackAckRef: Ref<boolean> = ref(readHostPackAcknowledged())

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === LS_PRODUCT_FLOW_HOST_ACK || e.key === buildTenantScopedStorageKey(LS_PRODUCT_FLOW_HOST_ACK)) {
      hostPackAckRef.value = readHostPackAcknowledged()
    }
  })
}

export function hostPackAcknowledgedRef(): Ref<boolean> {
  return hostPackAckRef
}

/**
 * Same-window localStorage writes do not emit a browser `storage` event.
 * Re-read the scoped acknowledgement after the profile/workspace preference
 * hydration so an already completed host does not keep the minimal sidebar
 * until the user refreshes the app.
 */
export function refreshHostPackAcknowledged(): void {
  hostPackAckRef.value = readHostPackAcknowledged()
}

export function markHostPackAcknowledged(): void {
  hostPackAckRef.value = true
  if (typeof localStorage === 'undefined') return
  try {
    const scope = resolveTenantStorageScopeFromRuntime()
    writeTenantScopedStorageItem(LS_PRODUCT_FLOW_HOST_ACK, '1', scope)
    if (scope === 'local') {
      localStorage.setItem(LS_PRODUCT_FLOW_HOST_ACK, '1')
    }
  } catch {
    /* ignore */
  }
  void import('@/utils/workspacePrefsApi')
    .then(({ queueWorkspacePrefsSync }) => {
      queueWorkspacePrefsSync({ host_pack_acknowledged: true })
    })
    .catch(() => {})
}

export function resetProductFlowState(): void {
  hostPackAckRef.value = false
  if (typeof localStorage === 'undefined') return
  try {
    const scope = resolveTenantStorageScopeFromRuntime()
    removeTenantScopedStorageItem(LS_PRODUCT_FLOW_COMPLETED, scope)
    removeTenantScopedStorageItem(LS_PRODUCT_FLOW_HOST_ACK, scope)
    removeTenantScopedStorageItem(LS_PRODUCT_FLOW_PENDING_PROMPT, scope)
    removeTenantScopedStorageItem(LS_PRODUCT_FLOW_FIRST_TASK_PENDING, scope)
    removeTenantScopedStorageItem(LS_PRODUCT_FLOW_FIRST_TASK_RUN_ID, scope)
    if (scope === 'local') {
      localStorage.removeItem(LS_PRODUCT_FLOW_COMPLETED)
      localStorage.removeItem(LS_PRODUCT_FLOW_HOST_ACK)
      localStorage.removeItem(LS_PRODUCT_FLOW_PENDING_PROMPT)
      localStorage.removeItem(LS_PRODUCT_FLOW_FIRST_TASK_PENDING)
      localStorage.removeItem(LS_PRODUCT_FLOW_FIRST_TASK_RUN_ID)
    }
  } catch {
    /* ignore */
  }
}

export function parseFlowStepQuery(raw: unknown): ProductFlowStepId {
  const s = String(raw || '')
    .trim()
    .toLowerCase()
  if (s === 'host-pack' || s === 'host') return 'host-pack'
  if (s === 'industry' || s === 'mod') return 'industry'
  if (s === 'seed-demo' || s === 'seed') return 'seed-demo'
  if (s === 'first-ai-task' || s === 'ai-demo') return 'first-ai-task'
  if (s === 'done' || s === 'finish') return 'done'
  return 'welcome'
}

export function queueFirstAiTaskPrompt(prompt: string): void {
  if (typeof localStorage === 'undefined') return
  const text = String(prompt || '').trim()
  if (!text) return
  try {
    const scope = resolveTenantStorageScopeFromRuntime()
    writeTenantScopedStorageItem(LS_PRODUCT_FLOW_PENDING_PROMPT, text, scope)
    writeTenantScopedStorageItem(LS_PRODUCT_FLOW_FIRST_TASK_PENDING, '1', scope)
    removeTenantScopedStorageItem(LS_PRODUCT_FLOW_FIRST_TASK_RUN_ID, scope)
    if (scope === 'local') localStorage.setItem(LS_PRODUCT_FLOW_PENDING_PROMPT, text)
    if (scope === 'local') {
      localStorage.setItem(LS_PRODUCT_FLOW_FIRST_TASK_PENDING, '1')
      localStorage.removeItem(LS_PRODUCT_FLOW_FIRST_TASK_RUN_ID)
    }
  } catch {
    /* ignore */
  }
}

function readScopedFlowValue(key: string): string {
  if (typeof localStorage === 'undefined') return ''
  try {
    const scope = resolveTenantStorageScopeFromRuntime()
    return String(
      readTenantScopedStorageItem(key, scope) ?? (scope === 'local' ? localStorage.getItem(key) : '') ?? '',
    ).trim()
  } catch {
    return ''
  }
}

export function isFirstAiTaskPending(): boolean {
  return readScopedFlowValue(LS_PRODUCT_FLOW_FIRST_TASK_PENDING) === '1'
}

/** Bind the onboarding attempt to the exact durable AgentRun created by its seeded prompt. */
export function bindPendingFirstAiTaskRun(runId: string, userText: string): boolean {
  const id = String(runId || '').trim()
  const text = String(userText || '')
  if (!id || !isFirstAiTaskPending() || !text.includes('新手第一单') || !text.includes('演示出货单')) return false
  try {
    const scope = resolveTenantStorageScopeFromRuntime()
    writeTenantScopedStorageItem(LS_PRODUCT_FLOW_FIRST_TASK_RUN_ID, id, scope)
    if (scope === 'local') localStorage.setItem(LS_PRODUCT_FLOW_FIRST_TASK_RUN_ID, id)
    return true
  } catch {
    return false
  }
}

export function readPendingFirstAiTaskRunId(): string {
  return readScopedFlowValue(LS_PRODUCT_FLOW_FIRST_TASK_RUN_ID)
}

export interface FirstAiTaskRunEvidence {
  run_id?: string
  status?: string
  intent?: string
  steps?: Array<{
    tool_id?: string
    action?: string
    status?: string
    params?: Record<string, unknown>
    output?: Record<string, unknown>
  }>
}

/**
 * Close onboarding only from the bound run's durable three-tool evidence.
 * Waiting approval, failed tools, another run, or a chat-only completion never qualifies.
 */
export function completeFirstAiTaskFromRun(run: FirstAiTaskRunEvidence): boolean {
  const boundRunId = readPendingFirstAiTaskRunId()
  if (!isFirstAiTaskPending() || !boundRunId || String(run.run_id || '').trim() !== boundRunId) return false
  if (String(run.status || '').trim() !== 'completed' || String(run.intent || '').trim() !== 'onboarding_first_order') return false
  const completedSteps = Array.isArray(run.steps)
    ? run.steps.filter((step) => String(step.status || '').trim() === 'completed' && step.output?.success === true)
    : []
  const hasCustomerRead = completedSteps.some(
    (step) => step.tool_id === 'business_db' && step.action === 'read' && step.params?.entity === 'customers',
  )
  const hasProductRead = completedSteps.some(
    (step) => step.tool_id === 'business_db' && step.action === 'read' && step.params?.entity === 'products',
  )
  const hasShipmentWrite = completedSteps.some(
    (step) => step.tool_id === 'business_db' && step.action === 'write' && step.params?.entity === 'shipment_records',
  )
  if (!hasCustomerRead || !hasProductRead || !hasShipmentWrite) return false
  try {
    const scope = resolveTenantStorageScopeFromRuntime()
    removeTenantScopedStorageItem(LS_PRODUCT_FLOW_FIRST_TASK_PENDING, scope)
    removeTenantScopedStorageItem(LS_PRODUCT_FLOW_FIRST_TASK_RUN_ID, scope)
    if (scope === 'local') {
      localStorage.removeItem(LS_PRODUCT_FLOW_FIRST_TASK_PENDING)
      localStorage.removeItem(LS_PRODUCT_FLOW_FIRST_TASK_RUN_ID)
    }
  } catch {
    return false
  }
  markProductFlowCompleted()
  return true
}

export function consumeFirstAiTaskPrompt(): string {
  if (typeof localStorage === 'undefined') return ''
  try {
    const scope = resolveTenantStorageScopeFromRuntime()
    const text =
      readTenantScopedStorageItem(LS_PRODUCT_FLOW_PENDING_PROMPT, scope) ??
      (scope === 'local' ? localStorage.getItem(LS_PRODUCT_FLOW_PENDING_PROMPT) : '')
    removeTenantScopedStorageItem(LS_PRODUCT_FLOW_PENDING_PROMPT, scope)
    if (scope === 'local') localStorage.removeItem(LS_PRODUCT_FLOW_PENDING_PROMPT)
    return String(text || '').trim()
  } catch {
    return ''
  }
}

export function readProductFlowLastStep(): ProductFlowStepId | null {
  if (typeof localStorage === 'undefined') return null
  try {
    const scope = resolveTenantStorageScopeFromRuntime()
    const scoped = readTenantScopedStorageItem(LS_PRODUCT_FLOW_LAST_STEP, scope)
    const raw = scoped ?? (scope === 'local' ? localStorage.getItem(LS_PRODUCT_FLOW_LAST_STEP) : null)
    if (!raw) return null
    const step = parseFlowStepQuery(raw)
    return step === 'welcome' && raw !== 'welcome' ? null : step
  } catch {
    return null
  }
}

export function saveProductFlowLastStep(step: ProductFlowStepId): void {
  if (typeof localStorage === 'undefined') return
  if (step === 'done') return
  try {
    const scope = resolveTenantStorageScopeFromRuntime()
    writeTenantScopedStorageItem(LS_PRODUCT_FLOW_LAST_STEP, step, scope)
    if (scope === 'local') {
      localStorage.setItem(LS_PRODUCT_FLOW_LAST_STEP, step)
    }
  } catch {
    /* ignore */
  }
}

/** 引导入口：URL ?step= 优先，否则续接上次步骤。 */
export function resolveProductFlowEntryStep(queryStep?: unknown): ProductFlowStepId {
  const explicit = String(queryStep ?? '').trim()
  if (explicit) return parseFlowStepQuery(queryStep)
  if (readProductFlowCompleted()) return 'done'
  return readProductFlowLastStep() || 'welcome'
}
