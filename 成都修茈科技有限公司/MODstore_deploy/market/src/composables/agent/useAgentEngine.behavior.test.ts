import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAgentStore } from '../../stores/agent'
import { useAuthStore } from '../../stores/auth'
import { xiaocLifeApi, type XiaoCLifeState } from '../../application/xiaocLifeApi'
import type { AgentSkill, LLMToolCall, SkillResult } from '../../types/agent'
import { useAgentEngine } from './useAgentEngine'

const mocks = vi.hoisted(() => {
  const successful = (message: string): Promise<SkillResult> => Promise.resolve({ success: true, message })
  return {
    agentButlerChat: vi.fn(),
    matchByIntent: vi.fn(),
    getById: vi.fn(),
    serializeVisibleDom: vi.fn(() => 'visible controls'),
    getPageContext: vi.fn(() => 'page context'),
    captureViewport: vi.fn(),
    executor: {
      navigate: vi.fn(() => successful('navigated')),
      click: vi.fn(() => successful('clicked')),
      fill: vi.fn(() => successful('filled')),
      select: vi.fn(() => successful('selected')),
      scroll: vi.fn(() => successful('scrolled')),
      read: vi.fn(() => successful('read page')),
      enhanceCurrentPage: vi.fn(() => successful('enhanced')),
    },
  }
})

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ fullPath: '/workbench/mod/testmod', name: 'mod-authoring' }),
}))

vi.mock('../../api', () => ({
  api: { agentButlerChat: mocks.agentButlerChat },
}))

vi.mock('../../utils/agent/agentSkillRegistry', () => ({
  skillRegistry: {
    matchByIntent: mocks.matchByIntent,
    getById: mocks.getById,
  },
}))

vi.mock('../../utils/agent/pageSerializer', () => ({
  serializeVisibleDom: mocks.serializeVisibleDom,
}))

vi.mock('./useActionExecutor', () => ({
  useActionExecutor: () => mocks.executor,
}))

vi.mock('./usePageAnalyzer', () => ({
  usePageAnalyzer: () => ({ getPageContext: mocks.getPageContext }),
}))

vi.mock('../../utils/agent/screenshotCapture', () => ({
  captureViewport: mocks.captureViewport,
}))

function tool(name: string, args: Record<string, unknown> = {}): LLMToolCall {
  return { id: `tool-${name}`, name, args }
}

function latestReply(): string | undefined {
  return useAgentStore().messages.at(-1)?.content
}

describe('useAgentEngine behavior', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    document.title = 'Market test'
    mocks.matchByIntent.mockReset().mockReturnValue(null)
    mocks.getById.mockReset().mockReturnValue(undefined)
    mocks.agentButlerChat.mockReset().mockResolvedValue({ text: 'LLM reply', tool_calls: [] })
    mocks.captureViewport.mockResolvedValue({
      ok: true,
      kind: 'image',
      dataUrl: 'data:image/png;base64,capture',
    })
  })

  it('管理端 L2 拒绝多工具批次，L1 也不能经离线技能绕过限制', async () => {
    const auth = useAuthStore()
    auth.user = { id: 11, username: 'admin', is_admin: true }
    auth.currentMode = 'admin'
    const read = vi.spyOn(xiaocLifeApi, 'read').mockResolvedValue({ scope: 'enterprise', level: 2 } as XiaoCLifeState)
    mocks.agentButlerChat.mockResolvedValue({ tool_calls: [tool('navigate', { name: 'plans' }), tool('click', { selector: '#buy' })] })
    const engine = useAgentEngine()
    await engine.handleInput('执行两个操作')
    expect(mocks.executor.navigate).not.toHaveBeenCalled()
    expect(mocks.executor.click).not.toHaveBeenCalled()
    expect(latestReply()).toContain('多步骤')
    const execute = vi.fn(async () => ({ success: true, message: 'should not run' }))
    mocks.matchByIntent.mockReturnValue({ id: 'builtin:navigate', execute } as unknown as AgentSkill)
    read.mockResolvedValue({ scope: 'enterprise', level: 1 } as XiaoCLifeState)
    mocks.agentButlerChat.mockResolvedValue({ text: '当前为对话模式，可以为你说明页面入口。', tool_calls: [] })
    await engine.handleInput('打开页面')
    expect(execute).not.toHaveBeenCalled()
    expect(latestReply()).toContain('可以为你说明页面入口')
  })

  it('ignores empty input and executes an offline skill without calling the LLM', async () => {
    const execute = vi.fn(async () => ({
      success: true,
      message: 'offline result',
      assistantReply: 'offline reply',
    }))
    mocks.matchByIntent.mockReturnValue({ execute } as unknown as AgentSkill)
    const engine = useAgentEngine()

    await engine.handleInput('   ')
    expect(useAgentStore().messages).toHaveLength(0)

    await engine.handleInput('run local skill')
    expect(execute).toHaveBeenCalledOnce()
    expect(mocks.agentButlerChat).not.toHaveBeenCalled()
    expect(latestReply()).toBe('offline reply')
    expect(useAgentStore().mode).toBe('idle')
  })

  it('builds text and uploaded-image LLM requests and persists the conversation id', async () => {
    mocks.agentButlerChat
      .mockResolvedValueOnce({ text: 'plain answer', conversation_id: 42 })
      .mockResolvedValueOnce({ text: 'image answer', tool_calls: [] })
    const engine = useAgentEngine()

    await engine.handleInput('plain request')
    const firstPayload = mocks.agentButlerChat.mock.calls[0]?.[0]
    expect(firstPayload.messages[0].role).toBe('system')
    expect(firstPayload.messages.at(-1)).toEqual({ role: 'user', content: 'plain request' })
    expect(useAgentStore().currentConversationId).toBe(42)
    expect(latestReply()).toBe('plain answer')

    await engine.handleInput('', { imageDataUrl: ' data:image/png;base64,upload ' })
    const secondPayload = mocks.agentButlerChat.mock.calls[1]?.[0]
    expect(secondPayload.messages.at(-1).content).toEqual([
      { type: 'text', text: '[图片]' },
      { type: 'image_url', image_url: { url: 'data:image/png;base64,upload', detail: 'low' } },
    ])
    expect(latestReply()).toBe('image answer')
  })

  it('captures a requested screenshot and reports an unavailable capture before calling the model', async () => {
    const engine = useAgentEngine()
    await engine.handleInput('inspect screenshot', { withScreenshot: true })
    expect(mocks.captureViewport).toHaveBeenCalledOnce()
    expect(mocks.agentButlerChat.mock.calls[0]?.[0].messages.at(-1).content).toEqual([
      { type: 'text', text: 'inspect screenshot' },
      { type: 'image_url', image_url: { url: 'data:image/png;base64,capture', detail: 'low' } },
    ])

    mocks.captureViewport.mockRejectedValueOnce(new Error('capture unavailable'))
    await engine.handleInput('inspect the missing screenshot', { withScreenshot: true })
    expect(mocks.agentButlerChat).toHaveBeenCalledOnce()
    expect(latestReply()).toContain('页面截图未取得')
    expect(useAgentStore().mode).toBe('error')
  })

  it.each([
    { ok: false, message: 'capture blocked', textFallback: 'page summary' },
    { ok: true, kind: 'text-snapshot', dataUrl: 'data:application/json;base64,summary' },
    { ok: true, kind: 'image', dataUrl: '' },
  ])('does not substitute text or an empty image for an explicitly requested screenshot: %j', async (capture) => {
    mocks.captureViewport.mockResolvedValueOnce(capture)
    await useAgentEngine().handleInput('read this screenshot', { withScreenshot: true })
    expect(mocks.agentButlerChat).not.toHaveBeenCalled()
    expect(latestReply()).toContain('页面截图未取得')
    expect(useAgentStore().isLoading).toBe(false)
  })

  it.each([
    ['navigate', { route: 'plans' }, 'navigate'],
    ['click', { selector: '#buy' }, 'click'],
    ['fill', { selector: '#name', value: 'Ada' }, 'fill'],
    ['select', { selector: '#tier', value: 'pro' }, 'select'],
    ['scroll', { direction: 'down' }, 'scroll'],
    ['read', {}, 'read'],
    ['enhance_current_page', { brief: 'improve it' }, 'enhanceCurrentPage'],
  ] as const)('dispatches the %s tool to its executor', async (name, args, executorName) => {
    mocks.agentButlerChat.mockResolvedValueOnce({ text: '', tool_calls: [tool(name, args)] })
    await useAgentEngine().handleInput(`invoke ${name}`)

    expect(mocks.executor[executorName]).toHaveBeenCalledOnce()
    expect(latestReply()).toBe(
      name === 'navigate'
        ? 'navigated'
        : name === 'click'
          ? 'clicked'
          : name === 'fill'
            ? 'filled'
            : name === 'select'
              ? 'selected'
              : name === 'scroll'
                ? 'scrolled'
                : name === 'read'
                  ? 'read page'
                  : 'enhanced',
    )
    expect(useAgentStore().mode).toBe('idle')
  })

  it('executes a registered E-Skill and reports unknown tools', async () => {
    const execute = vi.fn(async () => ({ success: true, message: 'skill result' }))
    mocks.getById.mockReturnValueOnce({ execute } as unknown as AgentSkill)
    mocks.agentButlerChat
      .mockResolvedValueOnce({ text: '', tool_calls: [tool('custom:skill', { value: 1 })] })
      .mockResolvedValueOnce({ text: '', tool_calls: [tool('missing:tool')] })
    const engine = useAgentEngine()

    await engine.handleInput('custom operation')
    expect(execute).toHaveBeenCalledWith(
      expect.objectContaining({
        route: '/workbench/mod/testmod',
        pageSummary: 'page context',
      }),
      { value: 1 },
    )
    expect(latestReply()).toBe('skill result')

    await engine.handleInput('unknown operation')
    expect(latestReply()).toBe('未知工具：missing:tool')
  })

  it('keeps a failed conversation available for a real model retry without error text in its history', async () => {
    const execute = vi.fn(async () => ({ success: true, message: 'fallback result' }))
    mocks.agentButlerChat.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ text: 'recovered reply' })
    mocks.matchByIntent.mockReturnValue({ execute } as unknown as AgentSkill)
    const engine = useAgentEngine()
    const store = useAgentStore()
    store.currentConversationId = 9

    await engine.handleInput('fallback-capable request')
    expect(latestReply()).toBe('出错了：offline')
    expect(execute).not.toHaveBeenCalled()

    await engine.handleInput('retry our conversation')
    expect(latestReply()).toBe('recovered reply')
    expect(mocks.agentButlerChat.mock.calls[1]?.[0].conversation_id).toBe(9)
    expect(
      mocks.agentButlerChat.mock.calls[1]?.[0].messages.some((message: { content: string }) => message.content.includes('offline')),
    ).toBe(false)
  })

  it('surfaces preprocessing errors and resets loading state', async () => {
    mocks.serializeVisibleDom.mockImplementationOnce(() => {
      throw new Error('DOM failed')
    })
    const engine = useAgentEngine()
    await engine.handleInput('trigger preprocessing')

    expect(latestReply()).toBe('出错了：DOM failed')
    expect(useAgentStore().mode).toBe('error')
    expect(useAgentStore().isLoading).toBe(false)
  })

  it('sends each user turn once and keeps loading placeholders out of model history', async () => {
    const engine = useAgentEngine()
    await engine.handleInput('first question')
    expect(mocks.agentButlerChat.mock.calls[0]?.[0].messages.slice(1)).toEqual([{ role: 'user', content: 'first question' }])
    await engine.handleInput('second question')
    expect(mocks.agentButlerChat.mock.calls[1]?.[0].messages.slice(1)).toEqual([
      { role: 'user', content: 'first question' },
      { role: 'assistant', content: 'LLM reply' },
      { role: 'user', content: 'second question' },
    ])
  })

  it('reuses a preinserted turn without repeating its user message', async () => {
    const store = useAgentStore()
    store.addMessage({ id: 'existing-user', role: 'user', content: 'already inserted', timestamp: 1 })
    store.addMessage({ id: 'existing-reply', role: 'assistant', content: '…', timestamp: 2, isLoading: true })
    await useAgentEngine().handleInput('already inserted', { skipUserInsert: true })
    expect(mocks.agentButlerChat.mock.calls[0]?.[0].messages.slice(1)).toEqual([{ role: 'user', content: 'already inserted' }])
    expect(store.messages.map((message) => message.id)).toEqual(['existing-user', 'existing-reply'])
    expect(latestReply()).toBe('LLM reply')
  })

  it('allows a real L1 conversation when a keyword also matches a page skill', async () => {
    const auth = useAuthStore()
    auth.user = { id: 11, username: 'admin', is_admin: true }
    auth.currentMode = 'admin'
    vi.spyOn(xiaocLifeApi, 'read').mockResolvedValue({ scope: 'enterprise', level: 1 } as XiaoCLifeState)
    const execute = vi.fn(async () => ({ success: true, message: 'must not execute' }))
    mocks.matchByIntent.mockReturnValue({ id: 'builtin:navigate', execute } as unknown as AgentSkill)
    mocks.agentButlerChat.mockResolvedValue({ text: '可以这样设计跳转按钮的代码。', tool_calls: [] })

    await useAgentEngine().handleInput('帮我写打开页面的按钮代码')

    expect(execute).not.toHaveBeenCalled()
    expect(mocks.agentButlerChat).toHaveBeenCalledOnce()
    expect(latestReply()).toBe('可以这样设计跳转按钮的代码。')
  })

  it('does not mark an empty model reply as a completed answer', async () => {
    mocks.agentButlerChat.mockResolvedValue({ text: '   ', tool_calls: [] })
    await useAgentEngine().handleInput('write an explanation')
    expect(latestReply()).toContain('未收到有效回复')
    expect(useAgentStore().mode).toBe('error')
    expect(useAgentStore().isLoading).toBe(false)
  })

  it('does not run a replacement skill after a dispatched model request fails', async () => {
    const execute = vi.fn(async () => ({ success: true, message: 'unexpected side effect' }))
    mocks.matchByIntent.mockReturnValue({ id: 'builtin:navigate', execute } as unknown as AgentSkill)
    mocks.agentButlerChat.mockRejectedValue(new Error('provider unavailable'))
    useAgentStore().currentConversationId = 9

    await useAgentEngine().handleInput('continue our discussion of page navigation')

    expect(execute).not.toHaveBeenCalled()
    expect(latestReply()).toContain('provider unavailable')
    expect(useAgentStore().mode).toBe('error')
    expect(useAgentStore().currentConversationId).toBe(9)
  })

  it('ignores concurrent submissions while the original turn is still pending', async () => {
    let finish!: (value: { text: string }) => void
    mocks.agentButlerChat.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve
      }),
    )
    const engine = useAgentEngine()
    const first = engine.handleInput('first question')
    const second = engine.handleInput('second via Enter or quick action')
    const count = mocks.agentButlerChat.mock.calls.length
    const messages = [...useAgentStore().messages]
    finish({ text: 'first answer' })
    await Promise.all([first, second])

    expect(count).toBe(1)
    expect(messages).toHaveLength(2)
    expect(useAgentStore().messages.map((message) => message.content)).toEqual(['first question', 'first answer'])
  })

  it('keeps a cleared conversation and its new pending turn separate from a late receipt', async () => {
    let finishOld!: (value: { text: string; conversation_id: number }) => void
    let finishNew!: (value: { text: string; conversation_id: number }) => void
    mocks.agentButlerChat
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finishOld = resolve
        }),
      )
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finishNew = resolve
        }),
      )
    const engine = useAgentEngine()
    const store = useAgentStore()
    const old = engine.handleInput('old question')
    store.clearMessages()
    const fresh = engine.handleInput('new question')
    finishOld({ text: 'old answer', conversation_id: 101 })
    await old
    const pending = { messages: [...store.messages], conversation: store.currentConversationId, loading: store.isLoading }
    finishNew({ text: 'new answer', conversation_id: 202 })
    await fresh

    expect(pending.conversation).toBeNull()
    expect(pending.loading).toBe(true)
    expect(pending.messages.at(-1)?.isLoading).toBe(true)
    expect(pending.messages.some((message) => message.content === 'old answer')).toBe(false)
    expect(store.currentConversationId).toBe(202)
    expect(store.messages.map((message) => message.content)).toEqual(['new question', 'new answer'])
  })

  it('clears account A data and rejects its late tool receipt after switching to account B', async () => {
    let finish!: (value: { text: string; conversation_id: number; tool_calls: LLMToolCall[] }) => void
    mocks.agentButlerChat.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve
      }),
    )
    const auth = useAuthStore()
    auth.user = { id: 11, username: 'A', is_admin: false }
    const engine = useAgentEngine()
    const store = useAgentStore()
    const request = engine.handleInput('account A question')
    auth.user = { id: 22, username: 'B', is_admin: false }
    const messagesAfterSwitch = [...store.messages]
    finish({ text: 'account A private reply', conversation_id: 101, tool_calls: [tool('navigate', { name: 'plans' })] })
    await request

    expect(messagesAfterSwitch).toEqual([])
    expect(store.messages).toEqual([])
    expect(store.currentConversationId).toBeNull()
    expect(mocks.executor.navigate).not.toHaveBeenCalled()
    expect(store.isLoading).toBe(false)
  })

  it('stops receiving the original turn and never executes its late tools', async () => {
    let finish!: (value: { text: string; tool_calls: LLMToolCall[] }) => void
    mocks.agentButlerChat.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve
      }),
    )
    const store = useAgentStore()
    const request = useAgentEngine().handleInput('pending request')
    const signal = mocks.agentButlerChat.mock.calls[0]?.[1] as AbortSignal | undefined
    const stop = (store as unknown as { stopRequest?: () => void }).stopRequest
    stop?.()
    finish({ text: '', tool_calls: [tool('navigate', { name: 'plans' })] })
    await request

    expect(stop).toBeTypeOf('function')
    expect(signal?.aborted).toBe(true)
    expect(mocks.executor.navigate).not.toHaveBeenCalled()
    expect(latestReply()).toContain('已停止接收')
    expect(store.isLoading).toBe(false)
  })
})
