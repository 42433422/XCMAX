import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  executeCorpIntakeMatch,
  matchCorpIntakeIntent,
  runCorpQuickTask,
  runIntakeFillFromMessage,
  runIntakeQuickTask,
} from './corpIntakeSkill'
import type { AgentContext } from '../../../types/agent'

vi.mock('../../../api', () => ({
  api: {
    agentCorpIntakeFill: vi.fn(),
  },
}))

vi.mock('../../../corp-butler/contactIntakeBridge', () => ({
  waitForBridge: vi.fn(),
  applyDraftSafe: vi.fn(() => true),
  scrollToIntake: vi.fn(),
}))

import { api } from '../../../api'
import { waitForBridge, applyDraftSafe, scrollToIntake } from '../../../corp-butler/contactIntakeBridge'

function ctx(message: string, route = '/contact.html'): AgentContext {
  return {
    route,
    pageTitle: '联系',
    pageSummary: '联系页',
    userMessage: message,
    history: [],
  }
}

function bridge(overrides: Record<string, unknown> = {}) {
  return {
    getState: () => ({ userRole: '', directions: [] } as never),
    goToStep: vi.fn(),
    applyDraft: vi.fn(),
    highlightField: vi.fn(),
    validateCurrentStep: () => true,
    buildMessage: () => '',
    isSubmitted: () => false,
    getCurrentStepId: () => 'profile',
    stepIds: () => ['profile', 'problem', 'workflow', 'contact', 'plan', 'review'],
    ...overrides,
  }
}

describe('corpIntakeSkill', () => {
  beforeEach(() => {
    vi.mocked(waitForBridge).mockReset()
    vi.mocked(applyDraftSafe).mockReset()
    vi.mocked(applyDraftSafe).mockReturnValue(true)
    vi.mocked(scrollToIntake).mockClear()
    vi.mocked(api.agentCorpIntakeFill).mockReset()
  })

  it('matches fill intent on contact page', () => {
    expect(matchCorpIntakeIntent(ctx('帮我填写需求问卷'))).toEqual({ kind: 'fill' })
    expect(matchCorpIntakeIntent(ctx('有哪些产品', '/index.html'))).toBeNull()
  })

  it('matches review and step intents', () => {
    expect(matchCorpIntakeIntent(ctx('提交前帮我核对'))).toEqual({ kind: 'review' })
    expect(matchCorpIntakeIntent(ctx('跳到联系方式'))).toEqual({ kind: 'step', stepId: 'contact' })
    expect(matchCorpIntakeIntent(ctx('跳到第 2 题'))).toEqual({ kind: 'step', stepId: 'problem' })
    expect(matchCorpIntakeIntent(ctx('跳到计划和预算怎么对接'))).toEqual({ kind: 'step', stepId: 'plan' })
    expect(matchCorpIntakeIntent(ctx('跳到日常流程怎么做'))).toEqual({ kind: 'step', stepId: 'workflow' })
    expect(matchCorpIntakeIntent(ctx('跳到最大的困扰是什么'))).toEqual({ kind: 'step', stepId: 'problem' })
    expect(matchCorpIntakeIntent(ctx('跳到认识我的岗位角色'))).toEqual({ kind: 'step', stepId: 'profile' })
    expect(matchCorpIntakeIntent(ctx('随便聊聊'))).toBeNull()
  })

  it('runs intake_fill task with preset prompt via API', async () => {
    vi.mocked(waitForBridge).mockResolvedValue({
      getState: () => ({ userRole: '', directions: [] } as never),
      goToStep: vi.fn(),
      applyDraft: vi.fn(),
      highlightField: vi.fn(),
      validateCurrentStep: () => true,
      buildMessage: () => '',
      isSubmitted: () => false,
      getCurrentStepId: () => 'profile',
      stepIds: () => ['profile'],
    })
    vi.mocked(api.agentCorpIntakeFill).mockResolvedValue({
      success: true,
      reply: '已预填',
      draft: { userRole: '业务或销售', roleSummary: '跟单录入' },
    })

    const result = await runCorpQuickTask({
      label: '贸易跟单',
      task: 'intake_fill',
      payload: { prompt: '我是贸易跟单' },
    })

    expect(api.agentCorpIntakeFill).toHaveBeenCalled()
    expect(applyDraftSafe).toHaveBeenCalled()
    expect(result?.assistantReply).toContain('已预填')
  })

  it('fills, executes, and handles unavailable or submitted bridges', async () => {
    vi.mocked(waitForBridge).mockResolvedValueOnce(null)
    await expect(runIntakeFillFromMessage('需求', '页面摘要')).resolves.toMatchObject({
      assistantReply: expect.stringContaining('问卷尚未就绪'),
    })
    expect(scrollToIntake).toHaveBeenCalled()

    vi.mocked(waitForBridge).mockResolvedValueOnce(bridge({ isSubmitted: () => true }) as never)
    await expect(runIntakeFillFromMessage('需求', '页面摘要')).resolves.toMatchObject({
      assistantReply: expect.stringContaining('已提交过'),
    })

    const fillBridge = bridge()
    vi.mocked(waitForBridge).mockResolvedValueOnce(fillBridge as never).mockResolvedValueOnce(fillBridge as never)
    vi.mocked(api.agentCorpIntakeFill).mockResolvedValueOnce({
      success: true,
      reply: '',
      draft: { directions: [], roleSummary: ' ' },
    })
    await expect(runIntakeFillFromMessage('需求', '页面摘要')).resolves.toMatchObject({
      assistantReply: expect.stringContaining('已根据您的描述预填问卷'),
    })

    vi.mocked(waitForBridge).mockReset()
    vi.mocked(waitForBridge).mockResolvedValueOnce(null)
    await expect(executeCorpIntakeMatch({ kind: 'review' }, ctx('核对'))).resolves.toMatchObject({
      assistantReply: expect.stringContaining('打开需求问卷'),
    })

    vi.mocked(waitForBridge).mockResolvedValueOnce(bridge({ isSubmitted: () => true }) as never)
    await expect(executeCorpIntakeMatch({ kind: 'step', stepId: 'plan' }, ctx('计划'))).resolves.toMatchObject({
      assistantReply: expect.stringContaining('需求问卷已提交'),
    })

    vi.mocked(waitForBridge).mockReset()
    const quickFillBridge = bridge()
    vi.mocked(waitForBridge).mockResolvedValue(quickFillBridge as never)
    vi.mocked(api.agentCorpIntakeFill).mockResolvedValueOnce({
      success: true,
      reply: '已写入',
      draft: { userRole: '负责人' },
    })
    await expect(executeCorpIntakeMatch({ kind: 'fill' }, ctx('帮我写入'))).resolves.toMatchObject({
      assistantReply: expect.stringContaining('已写入'),
    })
  })

  it('handles quick task bridge, prompt, navigation, and default branches', async () => {
    vi.mocked(waitForBridge).mockResolvedValueOnce(null)
    await expect(runIntakeQuickTask({ label: '跳步', task: 'intake_step', payload: { stepId: 'plan' } })).resolves.toMatchObject({
      assistantReply: expect.stringContaining('问卷加载中'),
    })

    vi.mocked(waitForBridge).mockReset()
    const quickFillBridge = bridge()
    vi.mocked(waitForBridge).mockResolvedValue(quickFillBridge as never)
    vi.mocked(api.agentCorpIntakeFill).mockResolvedValueOnce({
      success: true,
      reply: '按消息预填',
      draft: { roleSummary: '跟单' },
    })
    await expect(runIntakeQuickTask({ label: '填表', task: 'intake_fill', message: '我是销售' })).resolves.toMatchObject({
      assistantReply: expect.stringContaining('按消息预填'),
    })

    vi.mocked(waitForBridge).mockReset()
    const submitted = bridge({ isSubmitted: () => true })
    vi.mocked(waitForBridge).mockResolvedValueOnce(submitted as never)
    await expect(runIntakeQuickTask({ label: '默认步骤', task: 'intake_step', payload: {} })).resolves.toMatchObject({
      assistantReply: expect.stringContaining('profile'),
    })
    expect(submitted.goToStep).not.toHaveBeenCalled()

    vi.mocked(waitForBridge).mockResolvedValueOnce(submitted as never)
    await expect(runIntakeQuickTask({ label: '核对', task: 'intake_review', payload: {} })).resolves.toMatchObject({
      assistantReply: expect.stringContaining('核对页'),
    })

    await expect(runIntakeQuickTask({ label: '空链接', task: 'navigate', payload: {} })).resolves.toMatchObject({
      assistantReply: expect.stringContaining('请说明'),
    })
    vi.mocked(waitForBridge).mockResolvedValueOnce(bridge() as never)
    await expect(runIntakeQuickTask({ label: '未知', task: 'unknown' as never, payload: {} })).resolves.toBeNull()
  })

  it('navigate task assigns location', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { assign } as Location)
    const result = await runCorpQuickTask({
      label: '预约方案沟通',
      task: 'navigate',
      payload: { href: '/contact.html' },
    })
    expect(result?.assistantReply).toContain('预约')
    await new Promise((r) => setTimeout(r, 450))
    expect(assign).toHaveBeenCalledWith('/contact.html')
    vi.unstubAllGlobals()
  })
})
