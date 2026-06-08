import { describe, it, expect, beforeEach } from 'vitest'
import { skillRegistry } from './agentSkillRegistry'
import type { AgentSkill, AgentContext } from '../../types/agent'

// Reset registry state between tests by unregistering test skills
const TEST_IDS = ['test:navigate-reg', 'test:purchase-reg']

const mockSkill: AgentSkill = {
  id: 'test:navigate-reg',
  name: '导航技能',
  description: '测试导航',
  version: '1.0.0',
  trigger: {
    keywords: ['去', '跳转', '打开'],
    intent: ['navigate'],
  },
  permission: 'execute',
  metadata: { author: 'test', created_at: 0, evolution_count: 0, usage_count: 0 },
  execute: async () => ({ success: true, message: 'ok' }),
}

const mockHighRiskSkill: AgentSkill = {
  id: 'test:purchase-reg',
  name: '购买技能',
  description: '测试购买',
  version: '1.0.0',
  trigger: {
    keywords: ['购买', '升级会员', '买会员'],
    intent: ['purchase'],
    context: ['/plans'],
  },
  permission: 'full',
  metadata: { author: 'test', created_at: 0, evolution_count: 0, usage_count: 0 },
  execute: async () => ({ success: true, message: 'purchased' }),
}

describe('agentSkillRegistry', () => {
  beforeEach(() => {
    TEST_IDS.forEach((id) => skillRegistry.unregister(id))
  })

  it('register 和 getById 应一致', () => {
    skillRegistry.register(mockSkill)
    expect(skillRegistry.getById('test:navigate-reg')).toBe(mockSkill)
  })

  it('unregister 后 getById 返回 undefined', () => {
    skillRegistry.register(mockSkill)
    skillRegistry.unregister('test:navigate-reg')
    expect(skillRegistry.getById('test:navigate-reg')).toBeUndefined()
  })

  it('matchByIntent 应按关键词匹配', () => {
    skillRegistry.register(mockSkill)
    const ctx: AgentContext = {
      route: '/',
      pageTitle: '',
      pageSummary: '',
      userMessage: '帮我跳转到会员页面',
      history: [],
    }
    const match = skillRegistry.matchByIntent(ctx)
    expect(match?.id).toBe('test:navigate-reg')
  })

  it('matchByIntent 分数不足时应返回 null', () => {
    skillRegistry.register(mockSkill)
    const ctx: AgentContext = {
      route: '/',
      pageTitle: '',
      pageSummary: '',
      userMessage: '随机内容abc',
      history: [],
    }
    const match = skillRegistry.matchByIntent(ctx)
    expect(match?.id).not.toBe('test:navigate-reg')
  })

  it('getSkillsForContext 带 context 的技能只在匹配路由出现', () => {
    skillRegistry.register(mockHighRiskSkill)

    const plansSkills = skillRegistry.getSkillsForContext('/plans')
    const ids = plansSkills.map((s) => s.id)
    expect(ids).toContain('test:purchase-reg')

    const walletSkills = skillRegistry.getSkillsForContext('/wallet')
    const walletIds = walletSkills.map((s) => s.id)
    expect(walletIds).not.toContain('test:purchase-reg')
  })

  it('getAll 返回所有注册技能', () => {
    skillRegistry.register(mockSkill)
    skillRegistry.register(mockHighRiskSkill)
    const all = skillRegistry.getAll()
    const ids = all.map((s) => s.id)
    expect(ids).toContain('test:navigate-reg')
    expect(ids).toContain('test:purchase-reg')
  })
})
