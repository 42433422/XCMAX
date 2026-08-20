import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAgentStore } from '../../stores/agent'
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
    mocks.matchByIntent.mockReturnValue(null)
    mocks.getById.mockReturnValue(undefined)
    mocks.agentButlerChat.mockResolvedValue({ text: 'LLM reply', tool_calls: [] })
    mocks.captureViewport.mockResolvedValue({
      ok: true,
      kind: 'image',
      dataUrl: 'data:image/png;base64,capture',
    })
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
      .mockResolvedValueOnce({ text: '', tool_calls: [] })
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
    expect(latestReply()).toBe('好的。')
  })

  it('captures a requested screenshot and tolerates an unavailable capture', async () => {
    const engine = useAgentEngine()
    await engine.handleInput('inspect screenshot', { withScreenshot: true })
    expect(mocks.captureViewport).toHaveBeenCalledOnce()
    expect(mocks.agentButlerChat.mock.calls[0]?.[0].messages.at(-1).content).toEqual([
      { type: 'text', text: 'inspect screenshot' },
      { type: 'image_url', image_url: { url: 'data:image/png;base64,capture', detail: 'low' } },
    ])

    mocks.captureViewport.mockRejectedValueOnce(new Error('capture unavailable'))
    await engine.handleInput('continue without image', { withScreenshot: true })
    expect(mocks.agentButlerChat.mock.calls[1]?.[0].messages.at(-1)).toEqual({
      role: 'user',
      content: 'continue without image',
    })
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

  it('falls back to a skill or a connection message when the LLM fails', async () => {
    const execute = vi.fn(async () => ({ success: true, message: 'fallback result' }))
    mocks.agentButlerChat.mockRejectedValue(new Error('offline'))
    mocks.matchByIntent
      .mockReturnValueOnce(null)
      .mockReturnValueOnce({ execute } as unknown as AgentSkill)
      .mockReturnValueOnce(null)
      .mockReturnValueOnce(null)
    const engine = useAgentEngine()
    const store = useAgentStore()
    store.currentConversationId = 9

    await engine.handleInput('fallback-capable request')
    expect(latestReply()).toBe('fallback result')

    await engine.handleInput('no fallback available')
    expect(latestReply()).toContain('无法连接到 AI 大脑')
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
})
