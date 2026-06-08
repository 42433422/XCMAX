import { describe, expect, it } from 'vitest'
import {
  appendVoiceInject,
  buildOrchestrationStatusSummary,
  hasEmployeePlanContext,
  hasVoiceWorkIntent,
  inferUserGoalFromVoiceMessages,
  isLikelyShortProceedFragment,
  looksLikeEmployeeTaskDescription,
  routeVoiceUtterance,
} from './voiceUtteranceRouter'

describe('routeVoiceUtterance', () => {
  it('routes status query when orchestrating', () => {
    expect(
      routeVoiceUtterance({
        text: '做到哪了',
        orchPhase: 'running',
        hasPlanSession: false,
        hasPendingHandoff: false,
        canRunOrch: false,
        orchestrating: true,
      }).type,
    ).toBe('status_query')
  })

  it('routes cancel_work', () => {
    expect(
      routeVoiceUtterance({
        text: '取消制作',
        orchPhase: 'running',
        hasPlanSession: true,
        hasPendingHandoff: false,
        canRunOrch: false,
        orchestrating: true,
      }).type,
    ).toBe('cancel_work')
  })

  it('routes confirm when handoff ready', () => {
    expect(
      routeVoiceUtterance({
        text: '开始生成吧',
        orchPhase: 'idle',
        hasPlanSession: false,
        hasPendingHandoff: true,
        canRunOrch: true,
        orchestrating: false,
      }).type,
    ).toBe('confirm_generate')
  })

  it('routes inject during running orch', () => {
    expect(
      routeVoiceUtterance({
        text: '再加一个导出功能',
        orchPhase: 'running',
        hasPlanSession: false,
        hasPendingHandoff: false,
        canRunOrch: false,
        orchestrating: true,
      }).type,
    ).toBe('inject')
  })

  it('routes new_task when idle with work intent', () => {
    expect(
      routeVoiceUtterance({
        text: '做一个库存 Mod',
        orchPhase: 'idle',
        hasPlanSession: false,
        hasPendingHandoff: false,
        canRunOrch: false,
        orchestrating: false,
      }).type,
    ).toBe('new_task')
  })

  it('routes chat for casual speech when idle', () => {
    expect(
      routeVoiceUtterance({
        text: '听得到我说话吗',
        orchPhase: 'idle',
        hasPlanSession: false,
        hasPendingHandoff: false,
        canRunOrch: false,
        orchestrating: false,
      }).type,
    ).toBe('chat')
  })

  it('routes plan_reply when plan session active (not business confirm)', () => {
    expect(
      routeVoiceUtterance({
        text: '需要支持 Excel',
        orchPhase: 'idle',
        hasPlanSession: true,
        hasPendingHandoff: false,
        canRunOrch: false,
        planSessionPhase: 'chat',
        orchestrating: false,
      }).type,
    ).toBe('plan_reply')
    expect(
      routeVoiceUtterance({
        text: '开始',
        orchPhase: 'idle',
        hasPlanSession: true,
        hasPendingHandoff: false,
        canRunOrch: false,
        planSessionPhase: 'checklist',
        planIntentKey: 'employee',
        orchestrating: false,
        composerIntent: 'employee',
      }).type,
    ).toBe('plan_reply')
  })

  it('routes chat when user pushes back on early execution', () => {
    expect(
      routeVoiceUtterance({
        text: '你怎么就开始做了呢',
        orchPhase: 'idle',
        hasPlanSession: false,
        hasPendingHandoff: false,
        canRunOrch: false,
        orchestrating: false,
        composerIntent: 'employee',
      }).type,
    ).toBe('chat')
  })

  it('does not treat casual 员工 mention as work intent in employee mode', () => {
    expect(hasVoiceWorkIntent('这个员工是干什么的', { composerIntent: 'employee' })).toBe(false)
    expect(
      routeVoiceUtterance({
        text: '这个员工是干什么的',
        orchPhase: 'idle',
        hasPlanSession: false,
        hasPendingHandoff: false,
        canRunOrch: false,
        orchestrating: false,
        composerIntent: 'employee',
      }).type,
    ).toBe('chat')
  })

  it('routes new_task for explicit employee planning request', () => {
    expect(
      routeVoiceUtterance({
        text: '帮我规划一个负责库存的员工',
        orchPhase: 'idle',
        hasPlanSession: false,
        hasPendingHandoff: false,
        canRunOrch: false,
        orchestrating: false,
        composerIntent: 'employee',
      }).type,
    ).toBe('new_task')
  })

  it('routes chat for ASR noise fragment in employee mode', () => {
    expect(
      routeVoiceUtterance({
        text: '切空悲切',
        orchPhase: 'idle',
        hasPlanSession: false,
        hasPendingHandoff: false,
        canRunOrch: false,
        orchestrating: false,
        composerIntent: 'employee',
      }).type,
    ).toBe('chat')
  })
})

describe('looksLikeEmployeeTaskDescription', () => {
  it('detects word extract employee without explicit plan command', () => {
    expect(looksLikeEmployeeTaskDescription('我需要一个Word全量信息提取员工')).toBe(true)
  })
})

describe('isLikelyShortProceedFragment', () => {
  it('flags short affirmations without task semantics', () => {
    expect(isLikelyShortProceedFragment('嗯')).toBe(true)
    expect(isLikelyShortProceedFragment('开始')).toBe(true)
    expect(isLikelyShortProceedFragment('Word 全量提取员工包')).toBe(false)
  })
})

describe('hasEmployeePlanContext', () => {
  it('uses recent user messages when userGoal empty', () => {
    const messages = [
      { role: 'user', content: '识别 Word 文档里的所有信息' },
      { role: 'user', content: '全量提取并总结' },
    ]
    expect(hasEmployeePlanContext({}, messages, '开始规划')).toBe(true)
    expect(inferUserGoalFromVoiceMessages(messages, '开始规划')).toContain('Word')
  })
})

describe('appendVoiceInject', () => {
  it('appends inject line', () => {
    expect(appendVoiceInject('base', '加导出')).toBe('base\n【中途补充】加导出')
  })
})

describe('buildOrchestrationStatusSummary', () => {
  it('reports running step', () => {
    const s = buildOrchestrationStatusSummary([
      { label: '写代码', status: 'running' },
      { label: '测试', status: 'pending' },
    ])
    expect(s).toContain('写代码')
  })
})
