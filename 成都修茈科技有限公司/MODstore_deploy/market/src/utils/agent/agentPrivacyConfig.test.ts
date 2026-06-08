import { describe, expect, it } from 'vitest'
import { getRiskConfirmStrategy, buildActionPermission } from './agentPrivacyConfig'

describe('getRiskConfirmStrategy', () => {
  it('returns auto for low risk', () => {
    expect(getRiskConfirmStrategy('low')).toBe('auto')
  })

  it('returns preview for medium risk', () => {
    expect(getRiskConfirmStrategy('medium')).toBe('preview')
  })

  it('returns explicit for high risk', () => {
    expect(getRiskConfirmStrategy('high')).toBe('explicit')
  })
})

describe('buildActionPermission', () => {
  it('builds low risk permission with auto strategy', () => {
    const perm = buildActionPermission('navigate', 'low', '导航')
    expect(perm.action).toBe('navigate')
    expect(perm.risk).toBe('low')
    expect(perm.confirmStrategy).toBe('auto')
    expect(perm.confirmMessage).toBe('即将执行：导航')
  })

  it('builds medium risk permission with preview strategy', () => {
    const perm = buildActionPermission('click', 'medium', '点击按钮')
    expect(perm.confirmStrategy).toBe('preview')
    expect(perm.confirmMessage).toContain('可以取消')
  })

  it('builds high risk purchase permission with plan name', () => {
    const perm = buildActionPermission('purchase', 'high', '购买套餐', { planName: '专业版' })
    expect(perm.confirmStrategy).toBe('explicit')
    expect(perm.confirmMessage).toContain('专业版')
    expect(perm.confirmMessage).toContain('购买')
  })

  it('builds high risk purchase permission with plan_name fallback', () => {
    const perm = buildActionPermission('purchase', 'high', '购买', { plan_name: '企业版' })
    expect(perm.confirmMessage).toContain('企业版')
  })

  it('builds high risk purchase permission with default plan name', () => {
    const perm = buildActionPermission('purchase', 'high', '购买')
    expect(perm.confirmMessage).toContain('目标套餐')
  })

  it('builds high risk recharge permission with amount', () => {
    const perm = buildActionPermission('recharge', 'high', '充值', { amount: 100 })
    expect(perm.confirmMessage).toContain('¥100')
  })

  it('builds high risk recharge permission without amount', () => {
    const perm = buildActionPermission('recharge', 'high', '充值')
    expect(perm.confirmMessage).toContain('指定金额')
  })

  it('builds high risk generic permission', () => {
    const perm = buildActionPermission('delete', 'high', '删除数据')
    expect(perm.confirmMessage).toContain('高风险操作')
    expect(perm.confirmMessage).toContain('删除数据')
  })
})
