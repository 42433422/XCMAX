import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { buildActionPermission } from '../../utils/agent/agentPrivacyConfig'
import { getRiskConfirmStrategy } from '../../utils/agent/agentPrivacyConfig'

vi.mock('vue-router', () => ({ useRouter: () => ({}), useRoute: () => ({}) }))

describe('agentPrivacyConfig', () => {
  it('低风险 → auto', () => {
    expect(getRiskConfirmStrategy('low')).toBe('auto')
  })

  it('中风险 → preview', () => {
    expect(getRiskConfirmStrategy('medium')).toBe('preview')
  })

  it('高风险 → explicit', () => {
    expect(getRiskConfirmStrategy('high')).toBe('explicit')
  })

  it('buildActionPermission 生成正确 confirmMessage（购买）', () => {
    const perm = buildActionPermission('purchase', 'high', '购买 Pro', { planName: 'Pro' })
    expect(perm.confirmMessage).toContain('Pro')
    expect(perm.confirmStrategy).toBe('explicit')
  })

  it('buildActionPermission 生成正确 confirmMessage（点击）', () => {
    const perm = buildActionPermission('click', 'medium', '点击按钮')
    expect(perm.confirmStrategy).toBe('preview')
    expect(perm.confirmMessage).toContain('点击按钮')
  })

  it('buildActionPermission 低风险自动执行', () => {
    const perm = buildActionPermission('navigate', 'low', '跳转')
    expect(perm.confirmStrategy).toBe('auto')
  })
})

describe('usePrivacyManager', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('低风险动作不需要确认（requestAction 立即返回 true）', async () => {
    const { usePrivacyManager } = await import('./usePrivacyManager')
    const { requestAction } = usePrivacyManager()
    const result = await requestAction('navigate', 'low', '跳转测试')
    expect(result).toBe(true)
  })
})
