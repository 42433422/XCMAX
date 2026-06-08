import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { skillRegistry } from '../../utils/agent/agentSkillRegistry'
import { readPageSkill } from './skills/readPageSkill'
import type { AgentSkill, AgentContext } from '../../types/agent'

// 模拟 vue-router
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(), go: vi.fn() }),
  useRoute: () => ({ fullPath: '/workbench/mod/testmod', name: 'mod-authoring', params: { modId: 'testmod' } }),
}))

// 模拟 api
vi.mock('../../api', () => ({
  api: {
    agentButlerChat: vi.fn().mockResolvedValue({ text: '好的', tool_calls: [], conversation_id: 1 }),
    butlerOrchestrateStart: vi.fn().mockResolvedValue({ session_id: 'sess-xyz', status: 'running' }),
    workbenchGetSession: vi.fn().mockResolvedValue({ status: 'running', steps: [] }),
  },
}))

// 模拟 pageSerializer
vi.mock('../../utils/agent/pageSerializer', () => ({
  serializeVisibleDom: () => '当前页面: 测试',
}))

// 模拟 usePrivacyManager（让 requestAction 自动返回 false，阻止真实调用）
vi.mock('./usePrivacyManager', () => ({
  usePrivacyManager: () => ({
    requestAction: vi.fn().mockResolvedValue(false),
  }),
}))

describe('skillRegistry — 关键词匹配', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    skillRegistry.register(readPageSkill)
  })

  it('用户说"这里有什么" 应匹配 read_page 技能', () => {
    const ctx: AgentContext = {
      route: '/test',
      pageTitle: '测试',
      pageSummary: '',
      userMessage: '这里有什么？',
      history: [],
    }
    const match = skillRegistry.matchByIntent(ctx)
    expect(match).not.toBeNull()
    expect(match?.id).toBe('builtin:read_page')
  })

  it('用户说随机内容 不应匹配', () => {
    const ctx: AgentContext = {
      route: '/test',
      pageTitle: '测试',
      pageSummary: '',
      userMessage: 'xxxyyy随机内容',
      history: [],
    }
    const match = skillRegistry.matchByIntent(ctx)
    expect(match).toBeNull()
  })
})

describe('skillRegistry — tool_call 解析', () => {
  it('getById 能找到注册的技能', () => {
    skillRegistry.register(readPageSkill)
    expect(skillRegistry.getById('builtin:read_page')).toBeDefined()
  })

  it('getById 找不到未注册的技能', () => {
    expect(skillRegistry.getById('not:exist')).toBeUndefined()
  })
})

describe('readPageSkill — 执行', () => {
  it('execute 应返回 success=true', async () => {
    const ctx: AgentContext = {
      route: '/test',
      pageTitle: '测试',
      pageSummary: '',
      userMessage: '读取页面',
      history: [],
    }
    const result = await readPageSkill.execute(ctx)
    expect(result.success).toBe(true)
    expect(typeof result.message).toBe('string')
  })
})

describe('useActionExecutor — enhance_current_page', () => {
  it('用户取消时返回 success=false 且不调 butlerOrchestrateStart', async () => {
    const { useActionExecutor } = await import('./useActionExecutor')
    const { api } = await import('../../api')

    const executor = useActionExecutor()
    // requestAction is mocked to return false (user cancelled)
    const result = await executor.enhanceCurrentPage({ brief: '测试改写' })

    expect(result.success).toBe(false)
    expect(result.assistantReply).toContain('取消')
    expect((api as any).butlerOrchestrateStart).not.toHaveBeenCalled()
  })
})
