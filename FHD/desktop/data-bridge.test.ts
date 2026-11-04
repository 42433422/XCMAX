import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import type { Session } from 'electron'
import { describe, it, vi } from 'vitest'

vi.mock('electron', () => ({ app: { getPath: () => '/tmp/xcagi-test' } }))

import { queryOffline, resolveOfflineQuery } from './data-bridge'
import { queryOfflineForSession } from './data-bridge-session'

type Fixture = { dbPath: string; write: (sql: string) => void }

function withDb(name: string, check: (fixture: Fixture) => void | Promise<void>): void {
  it(name, async (context) => {
    let sqlite: typeof import('node:sqlite')
    try { sqlite = await import('node:sqlite') } catch { context.skip(); return }
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-offline-auth-'))
    const dbPath = path.join(dir, 'host.db')
    const write = (sql: string) => {
      const db = new sqlite.DatabaseSync(dbPath)
      try { db.exec(sql) } finally { db.close() }
    }
    try {
      write(`
        CREATE TABLE users(id INTEGER PRIMARY KEY, is_active INTEGER);
        INSERT INTO users VALUES (1, 1), (2, 1), (3, 0);
        CREATE TABLE sessions(session_id TEXT PRIMARY KEY, user_id INTEGER,
          expires_at TEXT, impersonating_market_user_id INTEGER);
        INSERT INTO sessions VALUES ('A', 1, '2099-01-01 00:00:00', NULL),
          ('B', 2, '2099-01-01T00:00:00+00:00', NULL),
          ('expired', 1, '2000-01-01 00:00:00', NULL),
          ('disabled', 3, '2099-01-01 00:00:00', NULL),
          ('impersonating', 1, '2099-01-01 00:00:00', 2);
        CREATE TABLE im_conversation_members(conversation_id INTEGER, user_id INTEGER);
        INSERT INTO im_conversation_members VALUES (10, 1), (20, 2);
        CREATE TABLE im_messages(id INTEGER PRIMARY KEY, conversation_id INTEGER,
          sender_user_id INTEGER, body TEXT, created_at TEXT);
        INSERT INTO im_messages VALUES (101, 10, 2, 'shared A room', '2026-01-01'),
          (202, 20, 2, 'shared B room', '2026-01-01');
        CREATE TABLE ai_employee_profiles(id INTEGER PRIMARY KEY, employee_id TEXT,
          user_id INTEGER, mod_id TEXT, display_name TEXT, avatar_url TEXT, created_at TEXT);
        INSERT INTO ai_employee_profiles VALUES (1, 'a', 1, 'm', 'shared A employee', '', '2026-01-01'),
          (2, 'b', 2, 'm', 'shared B employee', '', '2026-01-01');
      `)
      await check({ dbPath, write })
    } finally {
      fs.rmSync(dir, { recursive: true, force: true })
    }
  })
}

class CookieJar extends EventEmitter {
  token: string | null = 'A'
  reads = 0
  onRead?: (count: number) => void
  async get(filter: { url: string; name: string }) {
    assert.equal(filter.url, 'http://127.0.0.1:17500/')
    this.onRead?.(++this.reads)
    return this.token && filter.name === 'session_id'
      ? [{ name: 'session_id', value: this.token }] : []
  }
}

function fromJar(jar: CookieJar, dbPath: string) {
  return queryOfflineForSession(
    { cookies: jar } as unknown as Pick<Session, 'cookies'>,
    dbPath, { kind: 'chat_recent' }, 'http://127.0.0.1:17500/',
  )
}

describe('offline query authorization', () => {
  it('requires a resolved principal and clamps limits without accepting identity from params', () => {
    assert.equal(resolveOfflineQuery('chat_recent', { kind: 'chat_recent' }), null)
    for (const invalid of [0, -1, NaN, Infinity]) {
      assert.equal(resolveOfflineQuery('employees', { kind: 'employees' }, invalid), null)
    }
    for (const [limit, expected] of [[9999, 200], [0, 1], [NaN, 20]]) {
      assert.deepEqual(resolveOfflineQuery('chat_recent', { kind: 'chat_recent', limit }, 1)?.bind,
        [1, expected])
    }
    assert.equal(resolveOfflineQuery('search', { kind: 'search', keyword: ' ' }, 1), null)
    assert.equal(resolveOfflineQuery('unknown', { kind: 'unknown' }, 1), null)
  })

  it('requires a session token before probing database existence', async () => {
    assert.deepEqual(await queryOffline('/not/a/database', { kind: 'tables' }),
      { ok: false, error: 'auth_required' })
    assert.equal((await queryOffline('/not/a/database', { kind: 'tables' }, 'A')).error, 'db_missing')
  })

  withDb('checks conversation membership rather than sender identity', async ({ dbPath }) => {
    const a = await queryOffline(dbPath, { kind: 'chat_recent' }, 'A')
    const b = await queryOffline(dbPath, { kind: 'chat_recent' }, 'B')
    assert.equal(a.ok, true)
    assert.equal(b.ok, true)
    assert.deepEqual(a.data?.map(row => (row as { id: number }).id), [101])
    assert.deepEqual(b.data?.map(row => (row as { id: number }).id), [202])
  })

  withDb('scopes profiles and both search branches to the authenticated account', async ({ dbPath }) => {
    for (const token of ['A', 'B']) {
      const employees = await queryOffline(dbPath, { kind: 'employees' }, token)
      assert.equal(employees.data?.length, 1)
      assert.equal((employees.data?.[0] as { display_name: string }).display_name, `shared ${token} employee`)
      const search = await queryOffline(dbPath, { kind: 'search', keyword: 'shared' }, token)
      assert.equal(search.data?.length, 2)
      assert.ok(search.data?.every(row => (row as { text: string }).text.includes(` ${token} `)))
    }
  })

  withDb('denies missing, expired, disabled, unknown and impersonated identities', async ({ dbPath }) => {
    for (const token of [undefined, '', 'unknown', 'expired', 'disabled', 'impersonating']) {
      const result = await queryOffline(dbPath, { kind: 'chat_recent' }, token)
      assert.equal(result.ok, false)
      assert.equal(result.error, 'auth_required')
      assert.equal(result.data, undefined)
    }
  })

  withDb('rechecks logout and membership removal rather than caching the account', async ({ dbPath, write }) => {
    assert.equal((await queryOffline(dbPath, { kind: 'chat_recent' }, 'A')).ok, true)
    write('DELETE FROM im_conversation_members WHERE user_id = 1')
    assert.deepEqual((await queryOffline(dbPath, { kind: 'chat_recent' }, 'A')).data, [])
    write("DELETE FROM sessions WHERE session_id = 'A'")
    assert.equal((await queryOffline(dbPath, { kind: 'employees' }, 'A')).error, 'auth_required')
    assert.equal((await queryOffline(dbPath, { kind: 'employees' }, 'B')).ok, true)
  })

  withDb('cannot bypass authorization with renderer identity fields or SQL text', async ({ dbPath }) => {
    const params = { kind: 'employees', user_id: 2, sessionId: 'B' }
    const result = await queryOffline(dbPath, params, 'A')
    assert.deepEqual(result.data?.map(row => (row as { user_id: number }).user_id), [1])
    assert.equal((await queryOffline(dbPath, params)).error, 'auth_required')
    const search = await queryOffline(dbPath, { kind: 'search', keyword: "%' OR 1=1 --" }, 'A')
    assert.equal(search.ok, true)
    assert.deepEqual(search.data, [])
  })

  withDb('does not share identity across concurrent queries', async ({ dbPath }) => {
    const results = await Promise.all(Array.from({ length: 12 }, (_, i) =>
      queryOffline(dbPath, { kind: 'chat_recent' }, i % 2 ? 'B' : 'A')))
    results.forEach((result, i) => {
      assert.deepEqual(result.data?.map(row => (row as { id: number }).id), [i % 2 ? 202 : 101])
    })
  })

  withDb('fails closed on missing authorization schema and rejects unknown queries', async ({ dbPath, write }) => {
    assert.equal((await queryOffline(dbPath, { kind: 'unknown' }, 'A')).error, 'unsupported_kind')
    write('DROP TABLE sessions')
    const result = await queryOffline(dbPath, { kind: 'chat_recent' }, 'A')
    assert.deepEqual(result, { ok: false, error: 'query_failed' })
  })
})

describe('main-process session binding', () => {
  withDb('uses the sender cookie jar and removes its listener after success', async ({ dbPath }) => {
    const jar = new CookieJar()
    const result = await fromJar(jar, dbPath)
    assert.equal(result.ok, true)
    assert.deepEqual(result.data?.map(row => (row as { id: number }).id), [101])
    assert.equal(jar.listenerCount('changed'), 0)
  })

  withDb('drops in-flight rows on account switch, logout or same-cookie refresh', async ({ dbPath }) => {
    for (const next of ['B', null, 'A']) {
      const jar = new CookieJar()
      jar.onRead = count => {
        if (count === 2) {
          jar.token = next
          jar.emit('changed', {}, { name: 'session_id' })
        }
      }
      assert.deepEqual(await fromJar(jar, dbPath), { ok: false, error: 'auth_changed' })
      assert.equal(jar.listenerCount('changed'), 0)
    }
  })

  withDb('rechecks the cookie value even without a change event', async ({ dbPath }) => {
    const jar = new CookieJar()
    jar.onRead = count => { if (count === 2) jar.token = 'B' }
    assert.equal((await fromJar(jar, dbPath)).error, 'auth_changed')
  })

  withDb('fails closed when cookies are missing or unavailable and cleans up', async ({ dbPath }) => {
    const jar = new CookieJar()
    jar.token = null
    assert.equal((await fromJar(jar, dbPath)).error, 'auth_required')
    jar.onRead = () => { throw new Error('cookie store unavailable') }
    assert.equal((await fromJar(jar, dbPath)).error, 'auth_unavailable')
    assert.equal(jar.listenerCount('changed'), 0)
  })

  withDb('rejects non-loopback credential sources', async ({ dbPath }) => {
    const jar = new CookieJar()
    const result = await queryOfflineForSession(
      { cookies: jar } as unknown as Pick<Session, 'cookies'>,
      dbPath, { kind: 'chat_recent' }, 'https://example.com/',
    )
    assert.equal(result.error, 'auth_required')
    assert.equal(jar.reads, 0)
  })
})
