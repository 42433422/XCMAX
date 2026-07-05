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
  markHostPackAcknowledged,
  resetProductFlowState,
  parseFlowStepQuery,
  LS_PRODUCT_FLOW_COMPLETED,
  LS_PRODUCT_FLOW_HOST_ACK,
} from './productFlow'
import {
  buildTenantScopedStorageKey,
  invalidateTenantStorageScopeCache,
  setTenantStorageScopeCache,
} from '@/utils/tenantStorageScope'

describe('productFlow', () => {
  beforeEach(() => {
    localStorage.clear()
    invalidateTenantStorageScopeCache()
    setRuntimeOnboardingOpenIndustryIds(null)
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

  it('PRODUCT_FLOW_STEPS has 4 steps', () => {
    expect(PRODUCT_FLOW_STEPS).toHaveLength(4)
  })

  it('PRODUCT_FLOW_STEPS has correct step ids', () => {
    const ids = PRODUCT_FLOW_STEPS.map((s) => s.id)
    expect(ids).toContain('welcome')
    expect(ids).toContain('industry')
    expect(ids).toContain('host-pack')
    expect(ids).toContain('done')
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

  it('resetProductFlowState clears both localStorage keys', () => {
    markProductFlowCompleted()
    markHostPackAcknowledged()
    resetProductFlowState()
    expect(localStorage.getItem(LS_PRODUCT_FLOW_COMPLETED)).toBeNull()
    expect(localStorage.getItem(LS_PRODUCT_FLOW_HOST_ACK)).toBeNull()
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
