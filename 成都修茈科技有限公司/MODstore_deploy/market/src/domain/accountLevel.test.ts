import { describe, expect, it } from 'vitest'
import {
  buildLevelProfileDict,
  isMeAdminPayload,
  normalizeMeResponse,
  LEVEL_THRESHOLDS,
} from './accountLevel'

describe('accountLevel', () => {
  it('buildLevelProfileDict matches low tiers', () => {
    expect(buildLevelProfileDict(0).level).toBe(1)
    expect(buildLevelProfileDict(0).title).toBe('新手')
    expect(buildLevelProfileDict(1500).level).toBe(2)
    expect(buildLevelProfileDict(4999).level).toBe(2)
    expect(buildLevelProfileDict(5000).level).toBe(3)
  })

  it('buildLevelProfileDict returns max level for very high experience', () => {
    const profile = buildLevelProfileDict(999_999)
    expect(profile.level).toBe(7)
    expect(profile.title).toBe('传奇')
    expect(profile.next_level_min_exp).toBeNull()
    expect(profile.progress).toBe(1)
  })

  it('buildLevelProfileDict calculates progress between levels', () => {
    const profile = buildLevelProfileDict(3000)
    expect(profile.level).toBe(2)
    expect(profile.current_level_min_exp).toBe(1000)
    expect(profile.next_level_min_exp).toBe(5000)
    expect(profile.progress).toBeGreaterThan(0)
    expect(profile.progress).toBeLessThan(1)
  })

  it('buildLevelProfileDict handles null and undefined experience', () => {
    expect(buildLevelProfileDict(null).level).toBe(1)
    expect(buildLevelProfileDict(undefined).level).toBe(1)
  })

  it('buildLevelProfileDict handles negative experience', () => {
    expect(buildLevelProfileDict(-100).level).toBe(1)
    expect(buildLevelProfileDict(-100).experience).toBe(0)
  })

  it('buildLevelProfileDict handles NaN experience', () => {
    expect(buildLevelProfileDict(NaN).level).toBe(1)
  })

  it('buildLevelProfileDict handles string experience', () => {
    expect(buildLevelProfileDict('5000' as any).level).toBe(3)
  })

  it('buildLevelProfileDict at exact threshold boundary', () => {
    expect(buildLevelProfileDict(1000).level).toBe(2)
    expect(buildLevelProfileDict(20000).level).toBe(4)
    expect(buildLevelProfileDict(50000).level).toBe(5)
    expect(buildLevelProfileDict(100000).level).toBe(6)
    expect(buildLevelProfileDict(200000).level).toBe(7)
  })

  it('LEVEL_THRESHOLDS is strictly ascending by minExp and level', () => {
    // 铁律 6：不变式必须独立守护，防止阈值表被误改后无人察觉
    for (let i = 1; i < LEVEL_THRESHOLDS.length; i++) {
      const prev = LEVEL_THRESHOLDS[i - 1]!
      const curr = LEVEL_THRESHOLDS[i]!
      expect(curr.level).toBe(prev.level + 1)
      expect(curr.minExp).toBeGreaterThan(prev.minExp)
    }
    expect(LEVEL_THRESHOLDS[0]!.minExp).toBe(0)
  })

  it('buildLevelProfileDict progress is 0 at level floor', () => {
    // 边界值：exp === current_level_min_exp 时进度应为 0（铁律 3）
    const p2 = buildLevelProfileDict(1000)
    expect(p2.current_level_min_exp).toBe(1000)
    expect(p2.progress).toBe(0)

    const p3 = buildLevelProfileDict(5000)
    expect(p3.current_level_min_exp).toBe(5000)
    expect(p3.progress).toBe(0)
  })

  it('buildLevelProfileDict progress is clamped to [0, 1]', () => {
    // 边界值：脏数据 exp 超过 nextMin 时，progress 应被裁剪到 1（虽然外层逻辑会切换到下一档，此处守护 clamp）
    // 正常路径下不可能出现 exp > nextMin 但 level 仍是 current 的情况；这里只验证 Math.min 生效
    const p = buildLevelProfileDict(4999)
    expect(p.progress).toBeGreaterThanOrEqual(0)
    expect(p.progress).toBeLessThanOrEqual(1)
    // 4999 在 [1000, 5000) 区间，progress = (4999-1000)/(5000-1000) = 3999/4000 = 0.99975
    expect(p.progress).toBeCloseTo(0.99975, 4)
  })

  it('buildLevelProfileDict progress rounds to 4 decimal places', () => {
    // 验证 Math.round(progress * 10_000) / 10_000 的 4 位精度
    const p = buildLevelProfileDict(3000)
    // (3000-1000)/(5000-1000) = 2000/4000 = 0.5
    expect(p.progress).toBe(0.5)
    // 验证不超过 4 位小数
    const decimals = (String(p.progress).split('.')[1] ?? '').length
    expect(decimals).toBeLessThanOrEqual(4)
  })

  it('buildLevelProfileDict handles Infinity experience', () => {
    // 极端边界：Infinity 应被封顶到 level 7
    const p = buildLevelProfileDict(Infinity)
    expect(p.level).toBe(7)
    expect(p.progress).toBe(1)
    expect(p.next_level_min_exp).toBeNull()
  })

  it('buildLevelProfileDict handles very large number string', () => {
    // 类型边界：字符串数字应被正确转换
    expect(buildLevelProfileDict('999999' as any).level).toBe(7)
  })

  it('buildLevelProfileDict handles boolean experience (truthy/falsy edge)', () => {
    // 类型边界：布尔值 Number(true)=1, Number(false)=0
    expect(buildLevelProfileDict(true as any).experience).toBe(1)
    expect(buildLevelProfileDict(false as any).experience).toBe(0)
  })

  it('LEVEL_THRESHOLDS has 7 levels', () => {
    expect(LEVEL_THRESHOLDS).toHaveLength(7)
  })

  it('normalizes Java-style nested user', () => {
    const flat = normalizeMeResponse({
      user: { id: 9, username: 'a', email: 'a@b.c', is_admin: false, experience: 1200 },
    })
    if (!flat) throw new Error('expected flat to be non-null')
    expect(flat.id).toBe(9)
    expect(flat.username).toBe('a')
    expect(flat.experience).toBe(1200)
    expect(flat.is_admin).toBe(false)
  })

  it('normalizeMeResponse returns flat object as-is', () => {
    const flat = normalizeMeResponse({ id: 1, username: 'test', is_admin: true })
    if (!flat) throw new Error('expected flat to be non-null')
    expect(flat.id).toBe(1)
    expect(flat.username).toBe('test')
  })

  it('normalizeMeResponse handles null and undefined', () => {
    expect(normalizeMeResponse(null)).toBeNull()
    expect(normalizeMeResponse(undefined)).toBeUndefined()
  })

  it('normalizeMeResponse handles non-object', () => {
    // 非对象输入一律返回 null（语义：无效输入）；调用方应做 null 检查
    expect(normalizeMeResponse('string')).toBeNull()
    expect(normalizeMeResponse(123)).toBeNull()
    expect(normalizeMeResponse(true)).toBeNull()
  })

  it('normalizeMeResponse does not flatten when outer has id', () => {
    const input = { id: 1, username: 'outer', user: { id: 2, username: 'inner' } }
    const result = normalizeMeResponse(input)
    if (!result) throw new Error('expected result to be non-null')
    expect(result.id).toBe(1)
  })

  it('normalizeMeResponse uses admin field as is_admin fallback', () => {
    const flat = normalizeMeResponse({
      user: { id: 1, username: 'a', admin: true },
    })
    if (!flat) throw new Error('expected flat to be non-null')
    expect(flat.is_admin).toBe(true)
  })

  it('fails closed when desktop access is a false-like string', () => {
    const flat = normalizeMeResponse({
      user: { id: 2, username: 'pending', desktop_access: 'false' },
    })
    expect(flat?.desktop_access).toBe(false)
  })

  it('isMeAdminPayload reads nested admin', () => {
    expect(isMeAdminPayload({ user: { id: 1, username: 'x', is_admin: true } })).toBe(true)
    expect(isMeAdminPayload({ user: { id: 1, username: 'x', admin: true } })).toBe(true)
    expect(isMeAdminPayload({ id: 1, username: 'x', is_admin: true })).toBe(true)
    expect(isMeAdminPayload({ user: { id: 1, username: 'x', is_admin: false } })).toBe(false)
  })

  it('isMeAdminPayload returns false for non-admin', () => {
    expect(isMeAdminPayload(null)).toBe(false)
    expect(isMeAdminPayload(undefined)).toBe(false)
    expect(isMeAdminPayload({})).toBe(false)
    expect(isMeAdminPayload({ id: 1, is_admin: false })).toBe(false)
  })
})
