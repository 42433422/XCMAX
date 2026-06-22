import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  applyDraftSafe,
  describeDraftFields,
  getBridge,
  inferEarliestIncompleteStep,
  isContactPage,
  runContactAiAssistFill,
  scrollToIntake,
  waitForBridge,
  type ContactIntakeState,
  type XcContactIntake,
} from './corp-butler/contactIntakeBridge'

function fullState(overrides: Partial<ContactIntakeState> = {}): ContactIntakeState {
  return {
    userRole: '负责人',
    industry: '制造',
    roleSummary: '负责交付',
    primaryGoal: '减少重复沟通',
    directions: ['自动化'],
    manualSteps: '收集需求后人工分派',
    painGoals: '重复确认',
    sampleDesc: '样例',
    name: '张三',
    phone: '13800000000',
    email: 'demo@example.com',
    company: '修茈',
    timeline: '一个月',
    budget: '10万',
    needIntegration: '需要',
    integrationNote: 'ERP',
    extraNote: '尽快',
    ...overrides,
  }
}

function makeBridge(overrides: Partial<XcContactIntake> = {}): XcContactIntake {
  return {
    getState: vi.fn(() => fullState()),
    goToStep: vi.fn(),
    applyDraft: vi.fn(),
    highlightField: vi.fn(),
    validateCurrentStep: vi.fn(() => true),
    buildMessage: vi.fn(() => 'message'),
    isSubmitted: vi.fn(() => false),
    getCurrentStepId: vi.fn(() => 'profile'),
    stepIds: vi.fn(() => ['profile', 'problem', 'workflow', 'contact', 'plan', 'review']),
    ...overrides,
  }
}

afterEach(() => {
  delete window.XcContactIntake
  document.body.innerHTML = ''
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('contact intake bridge coverage', () => {
  it('detects contact page URLs and validates the bridge shape', () => {
    expect(isContactPage('/contact')).toBe(true)
    expect(isContactPage('/contact.html')).toBe(true)
    expect(isContactPage('/contact/')).toBe(true)
    expect(isContactPage('/about')).toBe(false)

    expect(getBridge()).toBeNull()
    window.XcContactIntake = { getState: vi.fn() } as unknown as XcContactIntake
    expect(getBridge()).toBeNull()

    const bridge = makeBridge()
    window.XcContactIntake = bridge
    expect(getBridge()).toBe(bridge)
  })

  it('infers the earliest incomplete step across the intake state', () => {
    expect(inferEarliestIncompleteStep(fullState({ userRole: '' }))).toBe('profile')
    expect(inferEarliestIncompleteStep(fullState({ roleSummary: '   ' }))).toBe('profile')
    expect(inferEarliestIncompleteStep(fullState({ primaryGoal: '' }))).toBe('problem')
    expect(inferEarliestIncompleteStep(fullState({ manualSteps: '' }))).toBe('workflow')
    expect(inferEarliestIncompleteStep(fullState({ painGoals: '' }))).toBe('workflow')
    expect(inferEarliestIncompleteStep(fullState({ name: '' }))).toBe('contact')
    expect(inferEarliestIncompleteStep(fullState({ email: '' }))).toBe('contact')
    expect(inferEarliestIncompleteStep(fullState({ timeline: '' }))).toBe('plan')
    expect(inferEarliestIncompleteStep(fullState({ needIntegration: '' }))).toBe('plan')
    expect(inferEarliestIncompleteStep(fullState())).toBe('review')
  })

  it('applies drafts safely and scrolls to the form', () => {
    document.body.innerHTML = '<section class="contact-intake-section"></section>'
    const scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      value: scrollIntoView,
      configurable: true,
    })
    const bridge = makeBridge({
      getState: vi.fn(() => fullState({ primaryGoal: '', manualSteps: '' })),
    })
    window.XcContactIntake = bridge

    expect(applyDraftSafe({ primaryGoal: '降本' })).toBe(true)
    expect(bridge.applyDraft).toHaveBeenCalledWith({ primaryGoal: '降本' })
    expect(bridge.goToStep).toHaveBeenCalledWith('workflow')
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' })

    vi.mocked(bridge.isSubmitted).mockReturnValue(true)
    expect(applyDraftSafe({ name: '李四' })).toBe(false)
    delete window.XcContactIntake
    expect(applyDraftSafe({ name: '王五' })).toBe(false)
  })

  it('waits for the bridge and times out when it never appears', async () => {
    vi.useFakeTimers()
    const bridge = makeBridge()
    const pending = waitForBridge(400)
    window.setTimeout(() => {
      window.XcContactIntake = bridge
    }, 160)

    await vi.advanceTimersByTimeAsync(240)
    await expect(pending).resolves.toBe(bridge)

    delete window.XcContactIntake
    const missing = waitForBridge(160)
    await vi.advanceTimersByTimeAsync(240)
    await expect(missing).resolves.toBeNull()
  })

  it('runs contact AI assist fill through all user-facing branches', async () => {
    document.body.innerHTML = '<section class="contact-intake-section"></section>'
    const scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      value: scrollIntoView,
      configurable: true,
    })

    vi.useFakeTimers()
    const missing = runContactAiAssistFill('修茈', 'CRM')
    await vi.advanceTimersByTimeAsync(8080)
    await expect(missing).resolves.toEqual({
      ok: false,
      message: '问卷尚未就绪，请刷新页面后重试。',
    })
    expect(scrollIntoView).toHaveBeenCalled()
    vi.useRealTimers()

    window.XcContactIntake = makeBridge({ isSubmitted: vi.fn(() => true) })
    await expect(runContactAiAssistFill('修茈', 'CRM')).resolves.toEqual({
      ok: false,
      message: '您已提交过需求问卷，如需修改请通过电话或邮件联系我们。',
    })

    window.XcContactIntake = makeBridge()
    await expect(runContactAiAssistFill('修茈', 'CRM')).resolves.toEqual({
      ok: false,
      message: '预填功能未加载，请强制刷新页面（Cmd+Shift+R）后重试。',
    })

    const runAiAssistFill = vi.fn(async () => ({ ok: true, message: '已预填' }))
    window.XcContactIntake = makeBridge({ runAiAssistFill })
    await expect(runContactAiAssistFill(' ', 'CRM')).resolves.toEqual({
      ok: false,
      message: '请填写公司名称和系统 / 业务类型。',
    })
    await expect(runContactAiAssistFill(' 修茈 ', ' CRM ')).resolves.toEqual({
      ok: true,
      message: '已预填',
    })
    expect(runAiAssistFill).toHaveBeenCalledWith({ company: '修茈', system: 'CRM' })
  })

  it('describes filled draft fields and exposes direct scroll helper', () => {
    document.body.innerHTML = '<section class="contact-intake-section"></section>'
    const scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      value: scrollIntoView,
      configurable: true,
    })

    expect(describeDraftFields({
      userRole: '老板',
      directions: ['自动派单'],
      email: 'x@example.com',
      budget: ' ',
      extraNote: '',
    })).toEqual(['岗位角色', '期望方向', '邮箱'])

    scrollToIntake()
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' })
  })
})
