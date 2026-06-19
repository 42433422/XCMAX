import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { useAgentStore } from './stores/agent'
import { useAgentEngine } from './composables/agent/useAgentEngine'
import { useButlerOrchestrator } from './composables/agent/useButlerOrchestrator'
import { useCorpAgentEngine } from './composables/agent/useCorpAgentEngine'

const agentMocks = vi.hoisted(() => ({
  route: { name: 'plans' as any, fullPath: '/plans', params: {} as Record<string, unknown>, query: {} as Record<string, unknown> },
  router: { push: vi.fn(), replace: vi.fn(), go: vi.fn(), back: vi.fn() },
  api: {
    agentButlerChat: vi.fn(),
    butlerOrchestrateStart: vi.fn(),
    workbenchGetSession: vi.fn(),
    restoreModSnapshot: vi.fn(),
    agentCorpChat: vi.fn(),
  },
  executor: {
    navigate: vi.fn(async () => ({ success: true, message: 'navigated' })),
    click: vi.fn(async () => ({ success: true, message: 'clicked' })),
    fill: vi.fn(async () => ({ success: true, message: 'filled' })),
    select: vi.fn(async () => ({ success: true, message: 'selected' })),
    scroll: vi.fn(async () => ({ success: true, message: 'scrolled' })),
    read: vi.fn(async () => ({ success: true, message: 'read page' })),
    enhanceCurrentPage: vi.fn(async () => ({ success: true, message: 'enhanced' })),
  },
  corpIntake: {
    matchCorpIntakeIntent: vi.fn(() => null),
    executeCorpIntakeMatch: vi.fn(async () => null),
    runIntakeFillFromMessage: vi.fn(async () => null),
    runCorpQuickTask: vi.fn(async () => null),
  },
  corpSite: {
    matchCorpSiteIntent: vi.fn(() => null),
  },
}))

vi.mock('vue-router', () => ({
  useRoute: () => agentMocks.route,
  useRouter: () => agentMocks.router,
}))

vi.mock('./api', () => ({ api: agentMocks.api }))

vi.mock('./composables/agent/useActionExecutor', () => ({
  useActionExecutor: () => agentMocks.executor,
}))

vi.mock('./composables/agent/usePageAnalyzer', () => ({
  usePageAnalyzer: () => ({ getPageContext: vi.fn(() => 'page analyzer context') }),
}))

vi.mock('./utils/agent/pageSerializer', () => ({
  serializeVisibleDom: vi.fn(() => '<main><button>购买</button><input /></main>'),
}))

vi.mock('./utils/agent/screenshotCapture', () => ({
  captureViewport: vi.fn(async () => 'data:image/png;base64,coverage'),
}))

vi.mock('./composables/agent/skills/corpIntakeSkill', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./composables/agent/skills/corpIntakeSkill')>()
  return {
    ...actual,
    matchCorpIntakeIntent: agentMocks.corpIntake.matchCorpIntakeIntent,
    executeCorpIntakeMatch: agentMocks.corpIntake.executeCorpIntakeMatch,
    runIntakeFillFromMessage: agentMocks.corpIntake.runIntakeFillFromMessage,
    runCorpQuickTask: agentMocks.corpIntake.runCorpQuickTask,
  }
})

vi.mock('./composables/agent/skills/corpSiteSkill', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./composables/agent/skills/corpSiteSkill')>()
  return {
    ...actual,
    matchCorpSiteIntent: agentMocks.corpSite.matchCorpSiteIntent,
  }
})

async function settle() {
  for (let i = 0; i < 5; i++) {
    await nextTick()
    await Promise.resolve()
  }
}

function lastMessage() {
  const store = useAgentStore()
  return store.messages[store.messages.length - 1]
}

beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  document.title = 'Coverage Page'
  Object.assign(agentMocks.route, { name: 'plans', fullPath: '/plans', params: {}, query: {} })
  for (const fn of Object.values(agentMocks.router)) fn.mockClear()
  for (const fn of Object.values(agentMocks.api)) fn.mockReset()
  for (const fn of Object.values(agentMocks.executor)) fn.mockClear()
  agentMocks.corpIntake.matchCorpIntakeIntent.mockReset().mockReturnValue(null)
  agentMocks.corpIntake.executeCorpIntakeMatch.mockReset().mockResolvedValue(null)
  agentMocks.corpIntake.runIntakeFillFromMessage.mockReset().mockResolvedValue(null)
  agentMocks.corpIntake.runCorpQuickTask.mockReset().mockResolvedValue(null)
  agentMocks.corpSite.matchCorpSiteIntent.mockReset().mockReturnValue(null)
  agentMocks.api.agentButlerChat.mockResolvedValue({ conversation_id: 'conv-ai', text: 'AI 回复' })
  agentMocks.api.butlerOrchestrateStart.mockResolvedValue({ session_id: 'sid-1', status: 'running' })
  agentMocks.api.workbenchGetSession.mockResolvedValue({ status: 'done', steps: [{ id: 's1', status: 'done' }], artifact: { ok: true } })
  agentMocks.api.restoreModSnapshot.mockResolvedValue({ ok: true })
  agentMocks.api.agentCorpChat.mockResolvedValue({ content: '官网 LLM 回复' })
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { pathname: '/services.html', search: '', origin: 'https://xiu-ci.com' },
  })
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('coverage useAgentEngine', () => {
  it('handles LLM replies, screenshots and tool calls', async () => {
    const engine = useAgentEngine()
    await engine.handleInput('帮我看看这个页面', { withScreenshot: true })
    await settle()
    expect(agentMocks.api.agentButlerChat).toHaveBeenCalledWith(expect.objectContaining({
      messages: expect.arrayContaining([expect.objectContaining({ role: 'user' })]),
      page_context: expect.any(String),
    }))
    expect(useAgentStore().currentConversationId).toBe('conv-ai')
    expect(lastMessage().content).toBe('AI 回复')

    const toolCases = [
      ['navigate', { route: 'wallet' }, 'navigated'],
      ['click', { selector: '#buy' }, 'clicked'],
      ['fill', { selector: 'input', value: 'abc' }, 'filled'],
      ['select', { selector: 'select', value: 'pro' }, 'selected'],
      ['scroll', { direction: 'down' }, 'scrolled'],
      ['read', {}, 'read page'],
      ['enhance_current_page', { brief: '改一下' }, 'enhanced'],
      ['unknown_tool', {}, '未知工具：unknown_tool'],
    ]
    for (const [name, args, expected] of toolCases) {
      agentMocks.api.agentButlerChat.mockResolvedValueOnce({ tool_calls: [{ name, args }] })
      await engine.handleInput(`run ${name}`)
      await settle()
      expect(lastMessage().content).toBe(expected)
    }
  })

  it('falls back cleanly on blank input and LLM errors', async () => {
    const engine = useAgentEngine()
    await engine.handleInput('   ')
    expect(useAgentStore().messages).toHaveLength(0)
    agentMocks.api.agentButlerChat.mockRejectedValueOnce(new Error('down'))
    await engine.handleInput('完全未知请求')
    await settle()
    expect(lastMessage().content).toContain('暂时无法连接')
  })
})

describe('coverage useButlerOrchestrator', () => {
  it('detects targets, starts sessions, polls and refreshes', async () => {
    Object.assign(agentMocks.route, { name: 'mod-authoring', fullPath: '/mods/mod-1', params: { modId: 'mod-1' }, query: {} })
    const orchestrator = useButlerOrchestrator()
    expect(orchestrator.detectTarget()).toEqual({ type: 'mod', id: 'mod-1' })
    agentMocks.api.workbenchGetSession
      .mockResolvedValueOnce({ status: 'running', steps: [{ id: 'a', status: 'done', started_at: 't1' }] })
      .mockResolvedValueOnce({ status: 'done', steps: [{ id: 'a', status: 'running' }, { id: 'b', status: 'done' }], artifact: { done: true } })
    await expect(orchestrator.start('请重构', 'frontend')).resolves.toEqual({ ok: true })
    await settle()
    expect(agentMocks.api.butlerOrchestrateStart).toHaveBeenCalledWith({ target_type: 'mod', target_id: 'mod-1', brief: '请重构', scope: 'frontend' })
    expect(useAgentStore().orchestrationSession?.status).toBe('running')
    await vi.advanceTimersByTimeAsync(1200)
    await settle()
    expect(useAgentStore().orchestrationSession?.status).toBe('done')
    expect(useAgentStore().orchestrationSession?.steps[0].status).toBe('done')
    orchestrator.refreshAfterDone()
    expect(agentMocks.router.go).toHaveBeenCalledWith(0)
    await orchestrator.rollbackToSnapshot('mod-1', 'snap-1')
    expect(agentMocks.api.restoreModSnapshot).toHaveBeenCalledWith('mod-1', 'snap-1')
  })

  it('covers no-target and start-error branches', async () => {
    Object.assign(agentMocks.route, { name: 'plans', fullPath: '/plans', params: {}, query: {} })
    const orchestrator = useButlerOrchestrator()
    expect(orchestrator.detectTarget()).toBeNull()
    await expect(orchestrator.start('brief')).resolves.toEqual(expect.objectContaining({ ok: false }))
    Object.assign(agentMocks.route, { name: 'workbench-shell', fullPath: '/workbench/workflow/9', params: { target: 'workflow', id: '9' }, query: {} })
    agentMocks.api.butlerOrchestrateStart.mockRejectedValueOnce(new Error('start failed'))
    await expect(orchestrator.start('brief')).resolves.toEqual({ ok: false, error: 'start failed' })
    expect(useAgentStore().mode).toBe('error')
  })
})

describe('coverage useCorpAgentEngine', () => {
  it('handles intake, site, fill, LLM and fallback replies', async () => {
    const engine = useCorpAgentEngine()
    agentMocks.corpIntake.matchCorpIntakeIntent.mockReturnValueOnce({ kind: 'contact' })
    agentMocks.corpIntake.executeCorpIntakeMatch.mockResolvedValueOnce({ assistantReply: '问卷匹配完成' })
    await engine.handleInput('我要预约')
    await settle()
    expect(lastMessage().content).toBe('问卷匹配完成')

    agentMocks.corpSite.matchCorpSiteIntent.mockReturnValueOnce({ assistantReply: '产品介绍回复' })
    await engine.handleInput('有哪些产品')
    await settle()
    expect(lastMessage().content).toBe('产品介绍回复')

    ;(window.location as any).pathname = '/contact.html'
    agentMocks.corpIntake.runIntakeFillFromMessage.mockResolvedValueOnce({ assistantReply: '已预填问卷' })
    await engine.handleInput('帮我填问卷 excel')
    await settle()
    expect(lastMessage().content).toBe('已预填问卷')

    ;(window.location as any).pathname = '/services.html'
    await engine.handleInput('普通官网问题')
    await settle()
    expect(lastMessage().content).toBe('官网 LLM 回复')

    agentMocks.api.agentCorpChat.mockRejectedValueOnce(new Error('corp down'))
    await engine.handleInput('再问一个普通问题')
    await settle()
    expect(lastMessage().content).toContain('我是修茈科技官网 AI 管家')
  })

  it('covers corp quick task branches and errors', async () => {
    const engine = useCorpAgentEngine()
    agentMocks.corpIntake.runCorpQuickTask.mockResolvedValueOnce({ assistantReply: '快捷任务完成' })
    await engine.runIntakeTask({ label: '预约', task: 'contact' } as any)
    await settle()
    expect(lastMessage().content).toBe('快捷任务完成')

    await engine.runIntakeTask({ label: '继续', task: '', message: '普通官网问题' } as any)
    await settle()
    expect(agentMocks.api.agentCorpChat).toHaveBeenCalled()

    agentMocks.corpIntake.runCorpQuickTask.mockRejectedValueOnce(new Error('quick failed'))
    await engine.runIntakeTask({ label: '失败', task: 'fail' } as any)
    await settle()
    expect(lastMessage().content).toContain('暂时无法处理')
  })
})
