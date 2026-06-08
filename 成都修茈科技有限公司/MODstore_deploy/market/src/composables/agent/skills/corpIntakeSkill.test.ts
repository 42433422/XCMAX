import { describe, it, expect, vi, beforeEach } from 'vitest'
import { matchCorpIntakeIntent, runCorpQuickTask } from './corpIntakeSkill'
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
import { waitForBridge, applyDraftSafe } from '../../../corp-butler/contactIntakeBridge'

function ctx(message: string, route = '/contact.html'): AgentContext {
  return {
    route,
    pageTitle: '联系',
    pageSummary: '联系页',
    userMessage: message,
    history: [],
  }
}

describe('corpIntakeSkill', () => {
  beforeEach(() => {
    vi.mocked(waitForBridge).mockReset()
    vi.mocked(applyDraftSafe).mockReset()
    vi.mocked(api.agentCorpIntakeFill).mockReset()
  })

  it('matches fill intent on contact page', () => {
    expect(matchCorpIntakeIntent(ctx('帮我填写需求问卷'))).toEqual({ kind: 'fill' })
    expect(matchCorpIntakeIntent(ctx('有哪些产品', '/index.html'))).toBeNull()
  })

  it('matches review and step intents', () => {
    expect(matchCorpIntakeIntent(ctx('提交前帮我核对'))).toEqual({ kind: 'review' })
    expect(matchCorpIntakeIntent(ctx('跳到联系方式'))).toEqual({ kind: 'step', stepId: 'contact' })
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
