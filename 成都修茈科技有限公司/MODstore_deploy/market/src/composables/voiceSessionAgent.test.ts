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
  isLikelyAsrEchoNoise,
  isPlaceholderPlanContent,
  isSummaryNeedsClarification,
  parseClassificationResponse,
  pickBestEmployeeBriefFromVoice,
  resetVoiceSessionState,
  sanitizeVoiceUtteranceText,
  useVoiceSessionAgent,
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

  it('parses fenced snake_case payloads, clamps confidence, and defaults invalid actions', () => {
    const parsed = parseClassificationResponse(`
\`\`\`json
{
  "action": "unknown_action",
  "reply_hint": "  继续追问  ",
  "state_patch": {
    "user_goal": "  数据员工  ",
    "open_questions": ["字段范围？"],
    "constraints": ["每天导出"],
    "stage": "executing",
    "last_user_tone": "cancel",
    "ready_to_plan": 1
  },
  "confidence": 2
}
\`\`\`
    `)
    expect(parsed?.action).toBe('chat')
    expect(parsed?.replyHint).toBe('继续追问')
    expect(parsed?.statePatch.userGoal).toBe('数据员工')
    expect(parsed?.statePatch.openQuestions).toEqual(['字段范围？'])
    expect(parsed?.statePatch.constraints).toEqual(['每天导出'])
    expect(parsed?.statePatch.stage).toBe('executing')
    expect(parsed?.statePatch.lastUserTone).toBe('cancel')
    expect(parsed?.statePatch.readyToPlan).toBe(true)
    expect(parsed?.confidence).toBe(1)
  })

  it('returns null for missing or malformed JSON objects', () => {
    expect(parseClassificationResponse('没有结构化内容')).toBeNull()
    expect(parseClassificationResponse('{bad json}')).toBeNull()
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

  it('uses fast classifier for empty text and routed commands, but not employee task text', () => {
    const state = createDefaultVoiceSessionState('employee')
    expect(
      shouldUseFastVoiceClassifier({
        text: '',
        state,
        recentMessages: [],
        routeCtx: baseRouteCtx,
        composerIntent: 'employee',
        provider: 'p',
        model: 'm',
      }),
    ).toBe(true)
    expect(
      shouldUseFastVoiceClassifier({
        text: '取消制作',
        state,
        recentMessages: [],
        routeCtx: baseRouteCtx,
        composerIntent: 'mod',
        provider: 'p',
        model: 'm',
      }),
    ).toBe(true)
    expect(
      shouldUseFastVoiceClassifier({
        text: '帮我做一个负责客户投诉分析并输出日报的员工',
        state,
        recentMessages: [],
        routeCtx: baseRouteCtx,
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

  it('routes cancel, status, injection, summary replies, and vague new tasks', () => {
    const state = createDefaultVoiceSessionState('employee')
    const makeCtx = (text: string, routeCtx = baseRouteCtx) => ({
      text,
      state,
      recentMessages: [],
      routeCtx,
      composerIntent: 'employee',
      provider: 'p',
      model: 'm',
    })

    expect(fallbackClassifyVoiceTurn(makeCtx('取消制作')).action).toBe('cancel_work')
    expect(
      fallbackClassifyVoiceTurn(makeCtx('现在进度怎么样了', { ...baseRouteCtx, hasPlanSession: true })).action,
    ).toBe('status')
    expect(
      fallbackClassifyVoiceTurn(makeCtx('再加一个导出 CSV', { ...baseRouteCtx, orchestrating: true })).action,
    ).toBe('chat')
    expect(
      fallbackClassifyVoiceTurn(
        makeCtx('把字段改成客户名称', { ...baseRouteCtx, hasPlanSession: true, planSessionPhase: 'summary' }),
      ).action,
    ).toBe('update_plan')
    expect(fallbackClassifyVoiceTurn(makeCtx('确认任务')).action).toBe('clarify')
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

  it('ignores empty patches and normalizes non-array fields plus metadata', () => {
    const state = createDefaultVoiceSessionState('employee')
    expect(applyVoiceSessionPatch(state, undefined)).toBe(state)
    expect(applyVoiceSessionPatch(state, {})).toBe(state)

    applyVoiceSessionPatch(state, {
      openQuestions: 'bad' as unknown as string[],
      constraints: 'bad' as unknown as string[],
      lastUserTone: 'confirm',
      planDismissedAt: 123,
      mode: 'mod',
    })
    expect(state.openQuestions).toEqual([])
    expect(state.constraints).toEqual([])
    expect(state.lastUserTone).toBe('confirm')
    expect(state.planDismissedAt).toBe(123)
    expect(state.mode).toBe('mod')

    applyVoiceSessionPatch(state, {
      openQuestions: ['  A  ', '', 'B', 'C', 'D', 'E', 'F', 'G'],
      constraints: ['  C1  ', '', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8', 'C9'],
    })
    expect(state.openQuestions).toEqual(['A', 'B', 'C', 'D', 'E', 'F'])
    expect(state.constraints).toEqual(['C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8'])
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

  it('includes questions, constraints, ready state, and extra hints', () => {
    const state = createDefaultVoiceSessionState('employee')
    state.readyToPlan = true
    state.openQuestions = ['对接哪个系统？']
    state.constraints = ['必须支持 CSV']
    const prompt = buildAgentAwarePrompt(state, '  只输出简短确认  ')
    expect(prompt).toContain('对接哪个系统？')
    expect(prompt).toContain('必须支持 CSV')
    expect(prompt).toContain('目标已基本清晰')
    expect(prompt).toContain('只输出简短确认')
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

  it('falls back to trigger or goal and avoids duplicating trigger already in transcript', () => {
    const state = createDefaultVoiceSessionState('employee')
    expect(buildPlanBriefFromVoiceMessages(state, [], '')).toBe('')
    expect(buildPlanBriefFromVoiceMessages(state, [], '开始规划')).toBe('【触发规划口令】\n开始规划')

    const brief = buildPlanBriefFromVoiceMessages(
      state,
      [{ role: 'user', content: '开始规划' }],
      '开始规划',
    )
    expect(brief.match(/开始规划/g)).toHaveLength(1)
  })
})

describe('isPlaceholderPlanContent', () => {
  it('detects empty reply and proceed commands', () => {
    expect(isPlaceholderPlanContent('（无回复）')).toBe(true)
    expect(isPlaceholderPlanContent('开始写吧')).toBe(true)
    expect(isPlaceholderPlanContent('Word 文档全量提取 JSON')).toBe(false)
  })

  it('detects short placeholders mixed with empty reply markers', () => {
    expect(isPlaceholderPlanContent('（无回复）好的')).toBe(true)
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

  it('prefers a non-placeholder state goal and returns empty when all chunks are filtered', () => {
    const state = createDefaultVoiceSessionState('employee')
    state.userGoal = '负责客户投诉归因分析并输出日报'
    expect(pickBestEmployeeBriefFromVoice(state, [{ role: 'user', content: '另一个需求' }])).toBe(
      '负责客户投诉归因分析并输出日报',
    )

    state.userGoal = ''
    expect(
      pickBestEmployeeBriefFromVoice(
        state,
        [
          { role: 'user', content: '开始写吧' },
          { role: 'assistant', content: '（无回复）' },
        ],
        '开始写吧',
      ),
    ).toBe('')
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

  it('returns empty for missing messages and filters ASR echo noise', () => {
    expect(formatFilteredPlanMessagesForBrief([])).toBe('')
    const text = formatFilteredPlanMessagesForBrief(
      [
        { role: 'user', content: 'Word 文档全量提取' },
        { role: 'user', content: '相处报备行程分享生活很珍贵' },
      ],
      'Word 文档全量提取 JSON',
    )
    expect(text).toContain('Word 文档全量提取')
    expect(text).not.toContain('相处报备')
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

describe('isLikelyAsrEchoNoise', () => {
  it('keeps short or task-like text and filters unrelated lifestyle echo in document threads', () => {
    expect(isLikelyAsrEchoNoise('短句', 'Word 文档')).toBe(false)
    expect(isLikelyAsrEchoNoise('Word 文档全量提取 JSON', 'Word 文档')).toBe(false)
    expect(isLikelyAsrEchoNoise('相处报备行程分享生活很珍贵', 'Word 文档全量提取')).toBe(true)
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

  it('falls back to an empty string when no state or utterance exists', () => {
    const state = createDefaultVoiceSessionState('employee')
    expect(buildPlanBriefFromSessionState(state, '')).toBe('')
  })
})

describe('useVoiceSessionAgent', () => {
  it('creates and resets a voice session ref', () => {
    const agent = useVoiceSessionAgent('mod')
    expect(agent.voiceSessionState.value.mode).toBe('mod')
    resetVoiceSessionState(agent.voiceSessionState, 'skill')
    expect(agent.voiceSessionState.value.mode).toBe('skill')
    expect(agent.voiceSessionState.value.stage).toBe('exploring')
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

  it('falls back when LLM returns invalid JSON and builds default classifier prompt for empty intent', async () => {
    vi.mocked(api.llmChat).mockResolvedValue({ content: 'not json' })
    const state = createDefaultVoiceSessionState('employee')
    const result = await classifyVoiceTurn({
      text: '数据报表怎么处理比较好',
      state,
      recentMessages: [
        { role: 'assistant', content: '你想处理哪些渠道？' },
        { role: 'user', content: '要处理企微和电话' },
      ],
      routeCtx: { ...baseRouteCtx, voiceTitle: '投诉员工', checklistLineCount: 2 },
      composerIntent: '',
      provider: 'openai',
      model: 'gpt-4o-mini',
    })
    expect(vi.mocked(api.llmChat)).toHaveBeenCalled()
    expect(String(vi.mocked(api.llmChat).mock.calls[0][2][0].content)).toContain('工作台模式：employee')
    expect(['open_plan', 'clarify', 'chat']).toContain(result.action)
  })
})
