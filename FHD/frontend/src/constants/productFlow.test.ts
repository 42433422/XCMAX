import { describe, it, expect, beforeEach } from 'vitest'
import {
  isTutorialReplayQuery,
  readOnboardingReturnPath,
  PRODUCT_FLOW_STEPS,
  ONBOARDING_OPEN_INDUSTRY_IDS,
  setRuntimeOnboardingOpenIndustryIds,
  readRuntimeOnboardingOpenIndustryIds,
  isOnboardingIndustryOpen,
  defaultOnboardingIndustryId,
  industryBaselineHint,
  readProductFlowCompleted,
  markProductFlowCompleted,
  readHostPackAcknowledged,
  hostPackAcknowledgedRef,
  refreshHostPackAcknowledged,
  markHostPackAcknowledged,
  resetProductFlowState,
  parseFlowStepQuery,
  LS_PRODUCT_FLOW_COMPLETED,
  LS_PRODUCT_FLOW_HOST_ACK,
  LS_PRODUCT_FLOW_PENDING_PROMPT,
  LS_PRODUCT_FLOW_FIRST_TASK_PENDING,
  LS_PRODUCT_FLOW_FIRST_TASK_RUN_ID,
  queueFirstAiTaskPrompt,
  cancelPendingFirstAiTask,
  consumeFirstAiTaskPrompt,
  isFirstAiTaskPending,
  bindPendingFirstAiTaskRun,
  completeFirstAiTaskFromRun,
} from './productFlow'
import { buildTenantScopedStorageKey, invalidateTenantStorageScopeCache, setTenantStorageScopeCache } from '@/utils/tenantStorageScope'

describe('productFlow', () => {
  beforeEach(() => {
    localStorage.clear()
    invalidateTenantStorageScopeCache()
    setRuntimeOnboardingOpenIndustryIds(null)
  })

  it('cancels only the current workspace pending first order without completing it', () => {
    setTenantStorageScopeCache('tenant-a')
    queueFirstAiTaskPrompt('新手第一单，演示出货单')
    expect(bindPendingFirstAiTaskRun('run-a', '新手第一单，演示出货单')).toBe(true)
    setTenantStorageScopeCache('tenant-b')
    queueFirstAiTaskPrompt('另一个工作区的首单')
    setTenantStorageScopeCache('tenant-a')
    cancelPendingFirstAiTask()
    expect(isFirstAiTaskPending()).toBe(false)
    expect(consumeFirstAiTaskPrompt()).toBe('')
    expect(localStorage.getItem(buildTenantScopedStorageKey(LS_PRODUCT_FLOW_FIRST_TASK_RUN_ID, 'tenant-a'))).toBeNull()
    expect(readProductFlowCompleted()).toBe(false)
    setTenantStorageScopeCache('tenant-b')
    expect(isFirstAiTaskPending()).toBe(true)
    expect(consumeFirstAiTaskPrompt()).toBe('另一个工作区的首单')
  })

  it('isTutorialReplayQuery returns true for tutorial', () => {
    expect(isTutorialReplayQuery('tutorial')).toBe(true)
    expect(isTutorialReplayQuery('Tutorial')).toBe(true)
    expect(isTutorialReplayQuery(' TUTORIAL ')).toBe(true)
  })

  it('isTutorialReplayQuery returns false for non-tutorial', () => {
    expect(isTutorialReplayQuery('step1')).toBe(false)
    expect(isTutorialReplayQuery(null)).toBe(false)
  })

  it('readOnboardingReturnPath returns path starting with /', () => {
    expect(readOnboardingReturnPath('/settings')).toBe('/settings')
  })

  it('readOnboardingReturnPath defaults to /', () => {
    expect(readOnboardingReturnPath('invalid')).toBe('/')
    expect(readOnboardingReturnPath('')).toBe('/')
  })

  it('PRODUCT_FLOW_STEPS includes demo data and the first AI task', () => {
    expect(PRODUCT_FLOW_STEPS).toHaveLength(6)
  })

  it('PRODUCT_FLOW_STEPS has correct step ids', () => {
    const ids = PRODUCT_FLOW_STEPS.map((s) => s.id)
    expect(ids).toEqual(['welcome', 'industry', 'host-pack', 'seed-demo', 'first-ai-task', 'done'])
    expect(ids).toContain('welcome')
    expect(ids).toContain('industry')
    expect(ids).toContain('host-pack')
    expect(ids).toContain('done')
  })

  it('parseFlowStepQuery preserves demo and first task steps', () => {
    expect(parseFlowStepQuery('seed-demo')).toBe('seed-demo')
    expect(parseFlowStepQuery('first-ai-task')).toBe('first-ai-task')
    expect(parseFlowStepQuery('ai-demo')).toBe('first-ai-task')
  })

  it('ONBOARDING_OPEN_INDUSTRY_IDS contains 涂料 and 考勤', () => {
    expect(ONBOARDING_OPEN_INDUSTRY_IDS).toContain('涂料')
    expect(ONBOARDING_OPEN_INDUSTRY_IDS).toContain('考勤')
  })

  it('readRuntimeOnboardingOpenIndustryIds returns default when not set', () => {
    const ids = readRuntimeOnboardingOpenIndustryIds()
    expect(ids).toEqual([...ONBOARDING_OPEN_INDUSTRY_IDS])
  })

  it('setRuntimeOnboardingOpenIndustryIds overrides defaults', () => {
    setRuntimeOnboardingOpenIndustryIds(['custom1', 'custom2'])
    expect(readRuntimeOnboardingOpenIndustryIds()).toEqual(['custom1', 'custom2'])
  })

  it('setRuntimeOnboardingOpenIndustryIds resets to default with empty array', () => {
    setRuntimeOnboardingOpenIndustryIds(['custom'])
    setRuntimeOnboardingOpenIndustryIds([])
    expect(readRuntimeOnboardingOpenIndustryIds()).toEqual([...ONBOARDING_OPEN_INDUSTRY_IDS])
  })

  it('isOnboardingIndustryOpen returns true for open industry', () => {
    expect(isOnboardingIndustryOpen('涂料')).toBe(true)
  })

  it('isOnboardingIndustryOpen returns false for closed industry', () => {
    expect(isOnboardingIndustryOpen('unknown')).toBe(false)
  })

  it('defaultOnboardingIndustryId returns 涂料', () => {
    expect(defaultOnboardingIndustryId()).toBe('涂料')
  })

  it('industryBaselineHint returns hint for known industry', () => {
    const hint = industryBaselineHint('涂料')
    expect(hint).toContain('涂料')
  })

  it('industryBaselineHint returns default hint for unknown', () => {
    const hint = industryBaselineHint('unknown')
    expect(hint).toContain('通用')
  })

  it('industryBaselineHint returns default hint for empty', () => {
    const hint = industryBaselineHint('')
    expect(hint).toBeTruthy()
  })

  it('readProductFlowCompleted returns false when not set', () => {
    expect(readProductFlowCompleted()).toBe(false)
  })

  it('markProductFlowCompleted sets localStorage', () => {
    markProductFlowCompleted()
    expect(localStorage.getItem(LS_PRODUCT_FLOW_COMPLETED)).toBe('1')
  })

  it('readProductFlowCompleted returns true after marking', () => {
    markProductFlowCompleted()
    expect(readProductFlowCompleted()).toBe(true)
  })

  it('readProductFlowCompleted ignores global flag in tenant scope', () => {
    setTenantStorageScopeCache('tenant:10')
    localStorage.setItem(LS_PRODUCT_FLOW_COMPLETED, '1')
    expect(readProductFlowCompleted()).toBe(false)
    localStorage.setItem(buildTenantScopedStorageKey(LS_PRODUCT_FLOW_COMPLETED, 'tenant:10'), '1')
    expect(readProductFlowCompleted()).toBe(true)
  })

  it('readHostPackAcknowledged returns false when not set', () => {
    expect(readHostPackAcknowledged()).toBe(false)
  })

  it('markHostPackAcknowledged sets localStorage', () => {
    markHostPackAcknowledged()
    expect(localStorage.getItem(LS_PRODUCT_FLOW_HOST_ACK)).toBe('1')
  })

  it('readHostPackAcknowledged ignores global flag in tenant scope', () => {
    setTenantStorageScopeCache('tenant:10')
    localStorage.setItem(LS_PRODUCT_FLOW_HOST_ACK, '1')
    expect(readHostPackAcknowledged()).toBe(false)
    localStorage.setItem(buildTenantScopedStorageKey(LS_PRODUCT_FLOW_HOST_ACK, 'tenant:10'), '1')
    expect(readHostPackAcknowledged()).toBe(true)
  })

  it('refreshes the reactive host acknowledgement after same-window scoped hydration', () => {
    setTenantStorageScopeCache('tenant:10')
    localStorage.setItem(buildTenantScopedStorageKey(LS_PRODUCT_FLOW_HOST_ACK, 'tenant:10'), '1')

    refreshHostPackAcknowledged()

    expect(hostPackAcknowledgedRef().value).toBe(true)
  })

  it('resetProductFlowState clears both localStorage keys', () => {
    markProductFlowCompleted()
    markHostPackAcknowledged()
    queueFirstAiTaskPrompt('test prompt')
    resetProductFlowState()
    expect(localStorage.getItem(LS_PRODUCT_FLOW_COMPLETED)).toBeNull()
    expect(localStorage.getItem(LS_PRODUCT_FLOW_HOST_ACK)).toBeNull()
    expect(localStorage.getItem(LS_PRODUCT_FLOW_PENDING_PROMPT)).toBeNull()
    expect(localStorage.getItem(LS_PRODUCT_FLOW_FIRST_TASK_PENDING)).toBeNull()
    expect(localStorage.getItem(LS_PRODUCT_FLOW_FIRST_TASK_RUN_ID)).toBeNull()
  })

  it('queues the first task once in tenant-scoped storage', () => {
    setTenantStorageScopeCache('tenant:10')
    queueFirstAiTaskPrompt('创建第一单')
    expect(localStorage.getItem(buildTenantScopedStorageKey(LS_PRODUCT_FLOW_PENDING_PROMPT, 'tenant:10'))).toBe('创建第一单')
    expect(localStorage.getItem(buildTenantScopedStorageKey(LS_PRODUCT_FLOW_FIRST_TASK_PENDING, 'tenant:10'))).toBe('1')
    expect(consumeFirstAiTaskPrompt()).toBe('创建第一单')
    expect(consumeFirstAiTaskPrompt()).toBe('')
    expect(isFirstAiTaskPending()).toBe(true)
  })

  it('completes onboarding only from the bound three-tool first-order run', () => {
    queueFirstAiTaskPrompt('这是我的新手第一单，请创建演示出货单')
    expect(bindPendingFirstAiTaskRun('run-first', '这是我的新手第一单，请创建演示出货单')).toBe(true)
    expect(
      completeFirstAiTaskFromRun({
        run_id: 'run-other',
        status: 'completed',
        intent: 'onboarding_first_order',
        steps: [],
      }),
    ).toBe(false)
    expect(readProductFlowCompleted()).toBe(false)

    const completed = completeFirstAiTaskFromRun({
      run_id: 'run-first',
      status: 'completed',
      intent: 'onboarding_first_order',
      steps: [
        {
          tool_id: 'business_db',
          action: 'read',
          status: 'completed',
          params: { entity: 'customers' },
          output: { success: true },
        },
        {
          tool_id: 'business_db',
          action: 'read',
          status: 'completed',
          params: { entity: 'products' },
          output: { success: true },
        },
        {
          tool_id: 'business_db',
          action: 'write',
          status: 'completed',
          params: { entity: 'shipment_records' },
          output: { success: true, data: { shipment_id: 30 } },
        },
      ],
    })

    expect(completed).toBe(true)
    expect(readProductFlowCompleted()).toBe(true)
    expect(isFirstAiTaskPending()).toBe(false)
    expect(localStorage.getItem(LS_PRODUCT_FLOW_FIRST_TASK_RUN_ID)).toBeNull()
  })

  it('does not close onboarding for a bound run that is waiting or missing a write', () => {
    queueFirstAiTaskPrompt('这是我的新手第一单，请创建演示出货单')
    bindPendingFirstAiTaskRun('run-first', '这是我的新手第一单，请创建演示出货单')

    expect(
      completeFirstAiTaskFromRun({
        run_id: 'run-first',
        status: 'waiting_user',
        intent: 'onboarding_first_order',
        steps: [],
      }),
    ).toBe(false)
    expect(isFirstAiTaskPending()).toBe(true)
    expect(readProductFlowCompleted()).toBe(false)
  })

  it('parseFlowStepQuery returns host-pack for host', () => {
    expect(parseFlowStepQuery('host-pack')).toBe('host-pack')
    expect(parseFlowStepQuery('host')).toBe('host-pack')
  })

  it('parseFlowStepQuery returns industry for mod', () => {
    expect(parseFlowStepQuery('industry')).toBe('industry')
    expect(parseFlowStepQuery('mod')).toBe('industry')
  })

  it('parseFlowStepQuery returns done for finish', () => {
    expect(parseFlowStepQuery('done')).toBe('done')
    expect(parseFlowStepQuery('finish')).toBe('done')
  })

  it('parseFlowStepQuery returns welcome by default', () => {
    expect(parseFlowStepQuery('')).toBe('welcome')
    expect(parseFlowStepQuery(null)).toBe('welcome')
    expect(parseFlowStepQuery(undefined)).toBe('welcome')
    expect(parseFlowStepQuery('random')).toBe('welcome')
  })

  it('parseFlowStepQuery is case-insensitive', () => {
    expect(parseFlowStepQuery('HOST-PACK')).toBe('host-pack')
    expect(parseFlowStepQuery('Industry')).toBe('industry')
  })
})
