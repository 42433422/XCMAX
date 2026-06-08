import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useCorpAgentEngine } from './useCorpAgentEngine'
import { useAgentStore } from '../../stores/agent'
import { api } from '../../api'

vi.mock('../../api', () => ({
  api: {
    agentCorpChat: vi.fn(),
    agentCorpIntakeFill: vi.fn(),
  },
}))

vi.mock('./skills/corpIntakeSkill', () => ({
  matchCorpIntakeIntent: vi.fn(() => null),
  executeCorpIntakeMatch: vi.fn(),
  runIntakeFillFromMessage: vi.fn(),
  runCorpQuickTask: vi.fn(),
  runIntakeQuickTask: vi.fn(),
}))

describe('useCorpAgentEngine', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    vi.mocked(api.agentCorpChat).mockReset()
    const intake = await import('./skills/corpIntakeSkill')
    vi.mocked(intake.matchCorpIntakeIntent).mockReturnValue(null)
    vi.mocked(intake.executeCorpIntakeMatch).mockReset()
    vi.stubGlobal('location', {
      pathname: '/index.html',
      search: '',
      origin: 'https://example.com',
    } as Location)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uses keyword reply without calling corp LLM', async () => {
    const { handleInput } = useCorpAgentEngine()
    await handleInput('你们有哪些产品？')
    expect(api.agentCorpChat).not.toHaveBeenCalled()
    const store = useAgentStore()
    const last = store.messages[store.messages.length - 1]
    expect(last.content).toContain('/services.html')
  })

  it('calls corp LLM when keyword misses', async () => {
    vi.mocked(api.agentCorpChat).mockResolvedValue({
      success: true,
      content: '这是 LLM 回答',
    })
    const { handleInput } = useCorpAgentEngine()
    await handleInput('今天天气怎么样')
    expect(api.agentCorpChat).toHaveBeenCalled()
    const store = useAgentStore()
    const last = store.messages[store.messages.length - 1]
    expect(last.content).toBe('这是 LLM 回答')
  })

  it('prefers intake skill on contact page when matched', async () => {
    const intake = await import('./skills/corpIntakeSkill')
    vi.mocked(intake.matchCorpIntakeIntent).mockReturnValue({ kind: 'review' })
    vi.mocked(intake.executeCorpIntakeMatch).mockResolvedValue({
      success: true,
      message: 'ok',
      assistantReply: '已跳转核对页',
    })
    vi.stubGlobal('location', {
      pathname: '/contact.html',
      search: '',
      origin: 'https://example.com',
    } as Location)

    const { handleInput } = useCorpAgentEngine()
    await handleInput('提交前核对')
    expect(intake.executeCorpIntakeMatch).toHaveBeenCalled()
    expect(api.agentCorpChat).not.toHaveBeenCalled()
    const store = useAgentStore()
    const last = store.messages[store.messages.length - 1]
    expect(last.content).toBe('已跳转核对页')
  })

  it('falls back when corp LLM fails', async () => {
    vi.mocked(api.agentCorpChat).mockRejectedValue(new Error('503'))
    const { handleInput } = useCorpAgentEngine()
    await handleInput('随便问问')
    const store = useAgentStore()
    const last = store.messages[store.messages.length - 1]
    expect(last.content).toContain('AI 管家')
  })
})
