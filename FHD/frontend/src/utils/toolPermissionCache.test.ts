import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  getToolPermission,
  setToolPermission,
  clearToolPermission,
  clearSessionPermissions,
  listAuthorizedTools,
} from './toolPermissionCache'

const SESSION_KEY = 'xcagi_tool_permissions_session'
const PERSIST_KEY = 'xcagi_tool_permissions_persistent'

describe('toolPermissionCache', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  it('returns null for unknown tool', () => {
    expect(getToolPermission('unknown_tool')).toBeNull()
  })

  it('returns null for empty toolId', () => {
    expect(getToolPermission('')).toBeNull()
    expect(getToolPermission('   ')).toBeNull()
  })

  it('stores and reads session scope', () => {
    setToolPermission('tool_a', 'session')
    expect(getToolPermission('tool_a')).toBe('session')
    // session 存在 sessionStorage
    const raw = sessionStorage.getItem(SESSION_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('tool_a')
  })

  it('stores and reads persistent scope', () => {
    setToolPermission('tool_b', 'persistent')
    expect(getToolPermission('tool_b')).toBe('persistent')
    // persistent 存在 localStorage
    const raw = localStorage.getItem(PERSIST_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('tool_b')
  })

  it('session takes precedence over persistent', () => {
    setToolPermission('tool_c', 'persistent')
    setToolPermission('tool_c', 'session')
    expect(getToolPermission('tool_c')).toBe('session')
  })

  it('clearToolPermission removes from both stores', () => {
    setToolPermission('tool_d', 'session')
    setToolPermission('tool_d', 'persistent')
    clearToolPermission('tool_d')
    expect(getToolPermission('tool_d')).toBeNull()
  })

  it('clearToolPermission ignores empty id', () => {
    setToolPermission('tool_e', 'session')
    clearToolPermission('')
    expect(getToolPermission('tool_e')).toBe('session')
  })

  it('clearSessionPermissions wipes session store only', () => {
    setToolPermission('tool_f', 'session')
    setToolPermission('tool_g', 'persistent')
    clearSessionPermissions()
    expect(getToolPermission('tool_f')).toBeNull()
    expect(getToolPermission('tool_g')).toBe('persistent')
  })

  it('listAuthorizedTools returns all authorized tools', () => {
    setToolPermission('tool_h', 'session')
    setToolPermission('tool_i', 'persistent')
    const list = listAuthorizedTools()
    const ids = list.map((x) => x.tool_id)
    expect(ids).toContain('tool_h')
    expect(ids).toContain('tool_i')
  })

  it('overwrites same tool on re-grant', () => {
    setToolPermission('tool_j', 'session')
    setToolPermission('tool_j', 'persistent')
    expect(getToolPermission('tool_j')).toBe('persistent')
    // session store 不应有 tool_j（被覆盖到 persistent）
    const sessionRaw = sessionStorage.getItem(SESSION_KEY) || '{}'
    expect(sessionRaw).not.toContain('tool_j')
  })

  it('survives corrupted storage data', () => {
    sessionStorage.setItem(SESSION_KEY, '{invalid json')
    localStorage.setItem(PERSIST_KEY, 'not json at all')
    expect(getToolPermission('any_tool')).toBeNull()
    // 写入应该不抛异常
    expect(() => setToolPermission('tool_k', 'session')).not.toThrow()
    expect(getToolPermission('tool_k')).toBe('session')
  })
})
