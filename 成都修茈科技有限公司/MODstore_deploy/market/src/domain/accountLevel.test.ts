import { describe, expect, it } from 'vitest'
import { buildLevelProfileDict, isMeAdminPayload, normalizeMeResponse, LEVEL_THRESHOLDS } from './accountLevel'

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

  it('LEVEL_THRESHOLDS has 7 levels', () => {
    expect(LEVEL_THRESHOLDS).toHaveLength(7)
  })

  it('normalizes Java-style nested user', () => {
    const flat = normalizeMeResponse({
      user: { id: 9, username: 'a', email: 'a@b.c', is_admin: false, experience: 1200 },
    })
    expect(flat.id).toBe(9)
    expect(flat.username).toBe('a')
    expect(flat.experience).toBe(1200)
    expect(flat.is_admin).toBe(false)
  })

  it('normalizeMeResponse returns flat object as-is', () => {
    const flat = normalizeMeResponse({ id: 1, username: 'test', is_admin: true })
    expect(flat.id).toBe(1)
    expect(flat.username).toBe('test')
  })

  it('normalizeMeResponse handles null and undefined', () => {
    expect(normalizeMeResponse(null)).toBeNull()
    expect(normalizeMeResponse(undefined)).toBeUndefined()
  })

  it('normalizeMeResponse handles non-object', () => {
    expect(normalizeMeResponse('string')).toBe('string')
  })

  it('normalizeMeResponse does not flatten when outer has id', () => {
    const input = { id: 1, username: 'outer', user: { id: 2, username: 'inner' } }
    const result = normalizeMeResponse(input)
    expect(result.id).toBe(1)
  })

  it('normalizeMeResponse uses admin field as is_admin fallback', () => {
    const flat = normalizeMeResponse({
      user: { id: 1, username: 'a', admin: true },
    })
    expect(flat.is_admin).toBe(true)
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
