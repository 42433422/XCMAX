import { describe, it, expect, beforeEach, vi } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

// vi.hoisted 回调在 import 初始化前执行，因此内部不能引用 fs/os/path；
// 用 holder 对象延迟解析 userDataDir，在 beforeEach 中赋值真实临时目录。
const state = vi.hoisted(() => {
  const holder: { userDataDir: string } = { userDataDir: '/tmp/xcagi-default' }
  return {
    holder,
    safeStorage: {
      isEncryptionAvailable: vi.fn(() => true),
      encryptString: vi.fn((plain: string) => Buffer.from(`enc::${plain}`)),
      decryptString: vi.fn((buf: Buffer) => buf.toString('utf8').replace(/^enc::/, '')),
    },
    app: {
      getPath: vi.fn(() => holder.userDataDir),
    },
  }
})

vi.mock('electron', () => ({
  app: state.app,
  safeStorage: state.safeStorage,
}))

import {
  setSecret,
  getSecret,
  deleteSecret,
  listSecrets,
  isSecretStoreAvailable,
} from './secure-store'

describe('secure-store — safeStorage 密钥链', () => {
  let userDataDir: string

  beforeEach(() => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'xs-'))
    userDataDir = path.join(tmp, 'userData')
    state.holder.userDataDir = userDataDir
    state.safeStorage.isEncryptionAvailable.mockReturnValue(true)
  })

  it('set/get roundtrip encrypts via safeStorage', () => {
    const set = setSecret('db_token', 'secret-value')
    expect(set.ok).toBe(true)
    const got = getSecret('db_token')
    expect(got).toEqual({ ok: true, value: 'secret-value' })
    // 落盘必须为密文，不得出现明文
    const raw = fs.readFileSync(path.join(userDataDir, 'secure', 'secrets.json'), 'utf8')
    expect(raw).not.toContain('secret-value')
    const file = JSON.parse(raw) as { entries: Record<string, string> }
    const stored = file.entries['db_token']
    expect(stored).toBeDefined()
    // 落盘为 base64 密文，解码后是 safeStorage 包裹结果（非明文）
    expect(Buffer.from(stored, 'base64').toString('utf8')).toBe('enc::secret-value')
  })

  it('get on missing key returns missing', () => {
    expect(getSecret('nope')).toEqual({ ok: false, error: 'missing' })
  })

  it('rejects when safeStorage unavailable', () => {
    state.safeStorage.isEncryptionAvailable.mockReturnValue(false)
    expect(setSecret('k', 'v')).toEqual({ ok: false, error: 'unavailable' })
    expect(getSecret('k')).toEqual({ ok: false, error: 'unavailable' })
  })

  it('rejects invalid keys', () => {
    expect(setSecret('../evil', 'v').ok).toBe(false)
    expect(setSecret('', 'v').ok).toBe(false)
    expect(getSecret('a/b').ok).toBe(false)
  })

  it('delete removes entry', () => {
    setSecret('a', '1')
    expect(deleteSecret('a')).toEqual({ ok: true })
    expect(getSecret('a')).toEqual({ ok: false, error: 'missing' })
    expect(deleteSecret('a')).toEqual({ ok: false, error: 'missing' })
  })

  it('lists keys', () => {
    setSecret('a', '1')
    setSecret('b', '2')
    const l = listSecrets()
    expect(l.ok && (l as { keys: string[] }).keys.sort()).toEqual(['a', 'b'])
  })

  it('isSecretStoreAvailable reflects safeStorage', () => {
    state.safeStorage.isEncryptionAvailable.mockReturnValue(false)
    expect(isSecretStoreAvailable()).toBe(false)
  })
})