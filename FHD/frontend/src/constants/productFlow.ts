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

/** 副窗「新手教程」默认路线 id（宿主三步引导，原基础教程） */
export const DEFAULT_TUTORIAL_TRACK_ID = 'basic'

export function isTutorialReplayQuery(raw: unknown): boolean {
  return String(raw || '').trim().toLowerCase() === 'tutorial'
}

export function readOnboardingReturnPath(raw: unknown): string {
  const p = String(raw || '').trim()
  if (p.startsWith('/')) return p
  return '/'
}

export type ProductFlowStepId = 'welcome' | 'host-pack' | 'industry' | 'done'

export interface ProductFlowStepMeta {
  id: ProductFlowStepId
  index: number
  title: string
  subtitle: string
}

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
    title: '补基础线',
    subtitle: '装侧栏宿主能力卡片（桥接 Mod），非 AI 员工；定制 Mod 才补员工',
  },
  {
    id: 'done',
    index: 4,
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
    通用:
      '通用场景：工作流员工、Planner 工具、企微与局域网入口等基础线，用到哪补哪即可。',
    涂料: '涂料/批发类：在通用基础线上，出货、客户、标签打印等行业 Mod 可按需从扩展市场安装。',
    批发: '批发分销：基础线装齐后，库存与客户相关 Mod 建议从扩展市场按需加载。',
    考勤:
      '考勤排班：先补 ERP 门面与表格工具侧栏，再装行业包；部门/人员与 AI 员工在账号定制 Mod。',
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
  void import('@/utils/workspacePrefsApi').then(({ queueWorkspacePrefsSync }) => {
    queueWorkspacePrefsSync({ product_flow_completed: true })
  }).catch(() => {})
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
    if (
      e.key === LS_PRODUCT_FLOW_HOST_ACK ||
      e.key === buildTenantScopedStorageKey(LS_PRODUCT_FLOW_HOST_ACK)
    ) {
      hostPackAckRef.value = readHostPackAcknowledged()
    }
  })
}

export function hostPackAcknowledgedRef(): Ref<boolean> {
  return hostPackAckRef
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
  void import('@/utils/workspacePrefsApi').then(({ queueWorkspacePrefsSync }) => {
    queueWorkspacePrefsSync({ host_pack_acknowledged: true })
  }).catch(() => {})
}

export function resetProductFlowState(): void {
  hostPackAckRef.value = false
  if (typeof localStorage === 'undefined') return
  try {
    const scope = resolveTenantStorageScopeFromRuntime()
    removeTenantScopedStorageItem(LS_PRODUCT_FLOW_COMPLETED, scope)
    removeTenantScopedStorageItem(LS_PRODUCT_FLOW_HOST_ACK, scope)
    if (scope === 'local') {
      localStorage.removeItem(LS_PRODUCT_FLOW_COMPLETED)
      localStorage.removeItem(LS_PRODUCT_FLOW_HOST_ACK)
    }
  } catch {
    /* ignore */
  }
}

export function parseFlowStepQuery(raw: unknown): ProductFlowStepId {
  const s = String(raw || '').trim().toLowerCase()
  if (s === 'host-pack' || s === 'host') return 'host-pack'
  if (s === 'industry' || s === 'mod') return 'industry'
  if (s === 'done' || s === 'finish') return 'done'
  return 'welcome'
}
