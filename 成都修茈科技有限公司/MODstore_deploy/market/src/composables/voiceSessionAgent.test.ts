import { describe, expect, it, vi, beforeEach } from 'vitest'
import {
  applyVoiceSessionPatch,
  buildAgentAwarePrompt,
  buildDefaultEmployeePlanAssistantReply,
  buildPlanBriefFromSessionState,
  buildPlanBriefFromVoiceMessages,
  classifyVoiceTurn,
  coerceClassificationForEmployee,
  createDefaultVoiceSessionState,
  fallbackClassifyVoiceTurn,
  shouldUseFastVoiceClassifier,
  formatFilteredPlanMessagesForBrief,
  isPlaceholderPlanContent,
  isSummaryNeedsClarification,
  parseClassificationResponse,
  pickBestEmployeeBriefFromVoice,
  sanitizeVoiceUtteranceText,
} from './voiceSessionAgent'

vi.mock('../api', () => ({
  api: {
    llmChat: vi.fn(),
  },
}))

import { api } from '../api'

const baseRouteCtx = {
  orchPhase: 'idle',
  hasPlanSession: false,
  hasPendingHandoff: false,
  canRunOrch: false,
  orchestrating: false,
}

describe('parseClassificationResponse', () => {
  it('parses JSON classification including pause_checklist', () => {
    const raw = JSON.stringify({
      action: 'pause_checklist',
      replyHint: '用户要求暂停',
      statePatch: { userGoal: '客服员工', readyToPlan: false },
      confidence: 0.85,
    })
    const parsed = parseClassificationResponse(raw)
    expect(parsed?.action).toBe('pause_checklist')
    expect(parsed?.replyHint).toContain('暂停')
    expect(parsed?.statePatch.userGoal).toBe('客服员工')
    expect(parsed?.confidence).toBe(0.85)
  })
})

describe('coerceClassificationForEmployee', () => {
  it('downgrades open_plan when not ready and low confidence', () => {
    const state = createDefaultVoiceSessionState('employee')
    const result = coerceClassificationForEmployee(
      {
        action: 'open_plan',
        replyHint: '',
        statePatch: {},
        confidence: 0.5,
      },
      state,
      { text: '嗯' },
    )
    expect(result.action).toBe('clarify')
  })

  it('allows open_plan when readyToPlan in patch', () => {
    const state = createDefaultVoiceSessionState('employee')
    const result = coerceClassificationForEmployee(
      {
        action: 'open_plan',
        replyHint: '',
        statePatch: { readyToPlan: true },
        confidence: 0.9,
      },
      state,
    )
    expect(result.action).toBe('open_plan')
  })

  it('maps pushback to dismiss_plan', () => {
    const state = createDefaultVoiceSessionState('employee')
    const result = coerceClassificationForEmployee(
      { action: 'chat', replyHint: '', statePatch: {}, confidence: 0.5 },
      state,
      { text: '你怎么就开始做了呢' },
    )
    expect(result.action).toBe('dismiss_plan')
    expect(result.statePatch.lastUserTone).toBe('complaint')
  })

  it('downgrades vague chat at checklist to clarify when low confidence', () => {
    const state = createDefaultVoiceSessionState('employee')
    const result = coerceClassificationForEmployee(
      { action: 'chat', replyHint: '', statePatch: {}, confidence: 0.4 },
      state,
      { text: '嗯', planSessionPhase: 'checklist' },
    )
    expect(result.action).toBe('clarify')
  })
})

describe('shouldUseFastVoiceClassifier', () => {
  it('never skips LLM when employee has plan session', () => {
    const state = createDefaultVoiceSessionState('employee')
    expect(
      shouldUseFastVoiceClassifier({
        text: '嗯',
        state,
        recentMessages: [],
        routeCtx: { ...baseRouteCtx, hasPlanSession: true, planSessionPhase: 'checklist' },
        composerIntent: 'employee',
        provider: 'p',
        model: 'm',
      }),
    ).toBe(false)
  })
})

describe('fallbackClassifyVoiceTurn', () => {
  it('routes pushback to chat not new_task', () => {
    const state = createDefaultVoiceSessionState('employee')
    const result = fallbackClassifyVoiceTurn({
      text: '你怎么就开始做了呢',
      state,
      recentMessages: [],
      routeCtx: baseRouteCtx,
      composerIntent: 'employee',
      provider: 'p',
      model: 'm',
    })
    expect(result.action).toBe('chat')
  })

  it('routes explicit employee plan to open_plan', () => {
    const state = createDefaultVoiceSessionState('employee')
    const result = fallbackClassifyVoiceTurn({
      text: '帮我规划一个负责库存的员工',
      state,
      recentMessages: [],
      routeCtx: baseRouteCtx,
      composerIntent: 'employee',
      provider: 'p',
      model: 'm',
    })
    expect(result.action).toBe('open_plan')
  })

  it('fallback confirm_plan at checklist for 开始', () => {
    const state = createDefaultVoiceSessionState('employee')
    const result = fallbackClassifyVoiceTurn({
      text: '开始啊',
      state,
      recentMessages: [],
      routeCtx: { ...baseRouteCtx, hasPlanSession: true, planSessionPhase: 'checklist' },
      composerIntent: 'employee',
      provider: 'p',
      model: 'm',
    })
    expect(result.action).toBe('confirm_plan')
  })

  it('fallback pause_checklist for 等一下', () => {
    const state = createDefaultVoiceSessionState('employee')
    const result = fallbackClassifyVoiceTurn({
      text: '等一下先别做',
      state,
      recentMessages: [],
      routeCtx: { ...baseRouteCtx, hasPlanSession: true, planSessionPhase: 'checklist' },
      composerIntent: 'employee',
      provider: 'p',
      model: 'm',
    })
    expect(result.action).toBe('pause_checklist')
  })

  it('routes casual complaint fragment to chat', () => {
    const state = createDefaultVoiceSessionState('employee')
    const result = fallbackClassifyVoiceTurn({
      text: '他这个会死',
      state,
      recentMessages: [],
      routeCtx: baseRouteCtx,
      composerIntent: 'employee',
      provider: 'p',
      model: 'm',
    })
    expect(result.action).toBe('chat')
  })
})

describe('applyVoiceSessionPatch', () => {
  it('merges goal and questions', () => {
    const state = createDefaultVoiceSessionState('employee')
    applyVoiceSessionPatch(state, {
      userGoal: '库存盘点员工',
      openQuestions: ['对接哪个系统？'],
      readyToPlan: true,
      stage: 'ready_to_plan',
    })
    expect(state.userGoal).toBe('库存盘点员工')
    expect(state.openQuestions).toEqual(['对接哪个系统？'])
    expect(state.readyToPlan).toBe(true)
    expect(state.stage).toBe('ready_to_plan')
  })
})

describe('buildAgentAwarePrompt', () => {
  it('includes user goal and forbids premature planning', () => {
    const state = createDefaultVoiceSessionState('employee')
    state.userGoal = '客服机器人'
    const prompt = buildAgentAwarePrompt(state)
    expect(prompt).toContain('客服机器人')
    expect(prompt).toContain('禁止')
  })
})

describe('buildPlanBriefFromVoiceMessages', () => {
  it('includes full voice transcript for planner', () => {
    const state = createDefaultVoiceSessionState('employee')
    state.userGoal = 'Word 全量提取为 JSON'
    const brief = buildPlanBriefFromVoiceMessages(
      state,
      [
        { role: 'user', content: 'undefined我想做Word提取助手' },
        { role: 'assistant', content: '需要包含表格吗？' },
        { role: 'user', content: '包括全部元素' },
      ],
      '开始规划',
    )
    expect(brief).toContain('【语音对话记录】')
    expect(brief).toContain('Word提取助手')
    expect(brief).not.toContain('undefined')
    expect(brief).toContain('开始规划')
  })

  it('filters unrelated ASR echo from word-extract thread', () => {
    const state = createDefaultVoiceSessionState('employee')
    state.userGoal = 'Word 全量提取为 JSON'
    const brief = buildPlanBriefFromVoiceMessages(
      state,
      [
        { role: 'user', content: 'Word 文档全量提取 JSON' },
        { role: 'user', content: '相处报备行程分享生活很珍贵' },
      ],
      '开始写吧',
    )
    expect(brief).toContain('Word 文档全量提取')
    expect(brief).not.toContain('相处报备')
  })
})

describe('isPlaceholderPlanContent', () => {
  it('detects empty reply and proceed commands', () => {
    expect(isPlaceholderPlanContent('（无回复）')).toBe(true)
    expect(isPlaceholderPlanContent('开始写吧')).toBe(true)
    expect(isPlaceholderPlanContent('Word 文档全量提取 JSON')).toBe(false)
  })
})

describe('pickBestEmployeeBriefFromVoice', () => {
  it('prefers substantive task description over noise', () => {
    const state = createDefaultVoiceSessionState('employee')
    const best = pickBestEmployeeBriefFromVoice(state, [
      { role: 'user', content: '（无回复）开始写吧' },
      { role: 'user', content: 'Word 文档全量提取为 JSON，含表格与图片' },
      { role: 'user', content: '相处报备行程分享生活' },
    ])
    expect(best).toContain('Word 文档全量提取')
    expect(best).not.toContain('相处报备')
  })
})

describe('formatFilteredPlanMessagesForBrief', () => {
  it('drops placeholders and mermaid blocks', () => {
    const text = formatFilteredPlanMessagesForBrief(
      [
        { role: 'user', content: 'Word 全量提取' },
        { role: 'assistant', content: '（无回复）' },
        { role: 'assistant', content: '```mermaid\ngraph TD\nA-->B\n```' },
      ],
      'Word 全量提取',
    )
    expect(text).toContain('Word 全量提取')
    expect(text).not.toContain('（无回复）')
    expect(text).not.toContain('mermaid')
  })
})

describe('buildDefaultEmployeePlanAssistantReply', () => {
  it('summarizes brief without placeholder', () => {
    const reply = buildDefaultEmployeePlanAssistantReply('Word 文档全量提取 JSON')
    expect(reply).toContain('Word 文档全量提取')
    expect(reply).toContain('document_full.json')
  })
})

describe('sanitizeVoiceUtteranceText', () => {
  it('strips undefined prefix from ASR/draft glitches', () => {
    expect(sanitizeVoiceUtteranceText('undefined我想做员工')).toBe('我想做员工')
  })
})

describe('buildPlanBriefFromSessionState', () => {
  it('prefers accumulated userGoal over raw utterance', () => {
    const state = createDefaultVoiceSessionState('employee')
    state.userGoal = '负责整理员工绩效摘要'
    const brief = buildPlanBriefFromSessionState(state, '开始吧')
    expect(brief).toContain('负责整理员工绩效摘要')
    expect(brief).toContain('开始吧')
  })
})

describe('isSummaryNeedsClarification', () => {
  it('detects pending clarification title', () => {
    expect(isSummaryNeedsClarification('待澄清', '需要说明职责')).toBe(true)
    expect(isSummaryNeedsClarification('库存员工', '负责盘点')).toBe(false)
  })
})

describe('classifyVoiceTurn', () => {
  beforeEach(() => {
    vi.mocked(api.llmChat).mockReset()
  })

  it('uses LLM JSON when available', async () => {
    vi.mocked(api.llmChat).mockResolvedValue({
      content: JSON.stringify({
        action: 'clarify',
        replyHint: '追问职责',
        statePatch: { userGoal: '数据分析员工' },
        confidence: 0.88,
      }),
    })
    const state = createDefaultVoiceSessionState('employee')
    const result = await classifyVoiceTurn({
      text: '我想做个看数据的',
      state,
      recentMessages: [],
      routeCtx: baseRouteCtx,
      composerIntent: 'employee',
      provider: 'openai',
      model: 'gpt-4o-mini',
    })
    expect(result.action).toBe('clarify')
    expect(result.statePatch.userGoal).toBe('数据分析员工')
  })

  it('falls back when LLM fails', async () => {
    vi.mocked(api.llmChat).mockRejectedValue(new Error('network'))
    const state = createDefaultVoiceSessionState('employee')
    const result = await classifyVoiceTurn({
      text: '切空悲切',
      state,
      recentMessages: [],
      routeCtx: baseRouteCtx,
      composerIntent: 'employee',
      provider: 'openai',
      model: 'gpt-4o-mini',
    })
    expect(result.action).toBe('chat')
  })
})
