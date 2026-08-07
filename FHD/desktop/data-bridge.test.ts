import { describe, it, expect, vi } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

vi.mock('electron', () => ({
  app: { getPath: () => '/tmp/xcagi-test' },
}))

import { resolveOfflineQuery, queryOffline } from './data-bridge'

describe('data-bridge — resolveOfflineQuery whitelist', () => {
  it('clamps limit into 1..200', () => {
    const high = resolveOfflineQuery('chat_recent', { kind: 'chat_recent', limit: 9999 })
    expect(high!.bind).toEqual([200])
    const low = resolveOfflineQuery('chat_recent', { kind: 'chat_recent', limit: 0 })
    expect(low!.bind).toEqual([1])
    const def = resolveOfflineQuery('chat_recent', { kind: 'chat_recent' })
    expect(def!.bind).toEqual([20])
  })

  it('tables returns a sqlite_master query', () => {
    const q = resolveOfflineQuery('tables', { kind: 'tables' })
    expect(q).not.toBeNull()
    expect(q!.sql).toContain('sqlite_master')
  })

  it('search with blank keyword returns null', () => {
    expect(resolveOfflineQuery('search', { kind: 'search', keyword: '   ' })).toBeNull()
  })

  it('search binds LIKE parameters', () => {
    const q = resolveOfflineQuery('search', { kind: 'search', keyword: 'abc' })
    expect(q).not.toBeNull()
    expect(q!.bind).toEqual(['%abc%', 20, '%abc%', 20])
  })

  it('unknown kind returns null', () => {
    expect(resolveOfflineQuery('nope', { kind: 'nope' })).toBeNull()
  })
})

describe('data-bridge — queryOffline', () => {
  it('returns db_missing when the db file is absent', async () => {
    const r = await queryOffline('/nonexistent/xcagi.db', { kind: 'tables' })
    expect(r.ok).toBe(false)
    expect(r.error).toBe('db_missing')
  })

  it('returns unsupported_kind for unknown kind against a real db', async () => {
    let DatabaseSync: any
    try {
      const mod = await import('node:sqlite')
      DatabaseSync = mod.DatabaseSync
    } catch {
      return // node:sqlite 不可用则跳过
    }
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xb-'))
    const dbPath = path.join(dir, 'xcagi.db')
    const db = new DatabaseSync(dbPath)
    db.exec('CREATE TABLE _t(id INTEGER)')
    db.close()
    try {
      const r = await queryOffline(dbPath, { kind: 'unknown_kind' })
      expect(r.ok).toBe(false)
      expect(r.error).toBe('unsupported_kind')
    } finally {
      fs.rmSync(dir, { recursive: true, force: true })
    }
  })

  it('reads chat / employees / search from a real sqlite db', async () => {
    let DatabaseSync: any
    try {
      const mod = await import('node:sqlite')
      DatabaseSync = mod.DatabaseSync
    } catch {
      return // node:sqlite 不可用则跳过
    }
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xb-'))
    const dbPath = path.join(dir, 'xcagi.db')
    const db = new DatabaseSync(dbPath)
    db.exec(
      `CREATE TABLE im_messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER, sender_user_id INTEGER,
        body TEXT, created_at TEXT
      )`,
    )
    db.exec(
      `INSERT INTO im_messages(conversation_id, sender_user_id, body, created_at)
       VALUES (1, 10, '离线测试消息', '2026-08-05 00:00:00')`,
    )
    db.exec(
      `CREATE TABLE ai_employee_profiles(
        id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT, user_id INTEGER,
        mod_id TEXT, display_name TEXT, avatar_url TEXT
      )`,
    )
    db.exec(
      `INSERT INTO ai_employee_profiles(employee_id, user_id, mod_id, display_name, avatar_url)
       VALUES ('emp1', 1, 'm1', '测试员工', '')`,
    )
    db.close()
    try {
      const chat = await queryOffline(dbPath, { kind: 'chat_recent', limit: 10 })
      expect(chat.ok).toBe(true)
      expect(chat.data!.length).toBe(1)
      expect((chat.data![0] as { body: string }).body).toBe('离线测试消息')

      const emps = await queryOffline(dbPath, { kind: 'employees', limit: 10 })
      expect(emps.ok).toBe(true)
      expect(emps.data!.length).toBe(1)
      expect((emps.data![0] as { display_name: string }).display_name).toBe('测试员工')

      const search = await queryOffline(dbPath, { kind: 'search', keyword: '离线' })
      expect(search.ok).toBe(true)
      expect(search.data!.some((r) => (r as { kind: string }).kind === 'message')).toBe(true)
    } finally {
      fs.rmSync(dir, { recursive: true, force: true })
    }
  })
})