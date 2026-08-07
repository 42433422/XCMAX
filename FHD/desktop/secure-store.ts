/**
 * 端侧密钥链（safeStorage 加解密）
 *
 * 用途：把 AI 供应商 API Key、DB 读写 Token、更新凭据等敏感配置从明文
 * （.env / localStorage）迁移到系统密钥链。macOS 走 Keychain、Windows 走 DPAPI，
 * Electron 内置 `safeStorage`，零外部原生依赖。
 *
 * 安全边界：
 * - 明文只存在于内存，落盘为 safeStorage 加密后的 base64（含随机 IV）。
 * - 存储文件模式 0600，仅本用户可读。
 * - `safeStorage.isEncryptionAvailable()` 为 false 时拒绝读写并明确报错，不静默降级成明文。
 * - key 白名单校验（非空、长度受限、禁止路径分隔符），避免异常 key 污染存储。
 */

import { app, safeStorage } from 'electron'
import fs from 'node:fs'
import path from 'node:path'

interface SecretFile {
  version: 1
  entries: Record<string, string>
}

export type SecretResult = { ok: true; value?: string } | { ok: false; error: string }

const MAX_KEY_LEN = 128

function secretsFilePath(): string {
  return path.join(app.getPath('userData'), 'secure', 'secrets.json')
}

export function isSecretStoreAvailable(): boolean {
  try {
    return safeStorage.isEncryptionAvailable()
  } catch {
    return false
  }
}

function isValidKey(key: string): boolean {
  return (
    typeof key === 'string' &&
    key.length > 0 &&
    key.length <= MAX_KEY_LEN &&
    !/[/\\]/.test(key)
  )
}

function loadFile(): SecretFile {
  try {
    const raw = fs.readFileSync(secretsFilePath(), 'utf8')
    const parsed = JSON.parse(raw) as SecretFile
    if (parsed && parsed.entries && typeof parsed.entries === 'object') {
      return parsed
    }
  } catch {
    /* 文件不存在或损坏 → 返回空 */
  }
  return { version: 1, entries: {} }
}

function saveFile(file: SecretFile): void {
  const dir = path.dirname(secretsFilePath())
  fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(secretsFilePath(), JSON.stringify(file), { mode: 0o600 })
}

function encrypt(plain: string): string {
  return safeStorage.encryptString(plain).toString('base64')
}

function decrypt(payload: string): string {
  return safeStorage.decryptString(Buffer.from(payload, 'base64'))
}

export function setSecret(key: string, value: string): SecretResult {
  if (!isValidKey(key)) return { ok: false, error: 'invalid_key' }
  if (!isSecretStoreAvailable()) return { ok: false, error: 'unavailable' }
  try {
    const file = loadFile()
    file.entries[key] = encrypt(String(value))
    saveFile(file)
    return { ok: true }
  } catch (e) {
    return { ok: false, error: `set_failed:${e instanceof Error ? e.message : String(e)}` }
  }
}

export function getSecret(key: string): SecretResult {
  if (!isValidKey(key)) return { ok: false, error: 'invalid_key' }
  if (!isSecretStoreAvailable()) return { ok: false, error: 'unavailable' }
  try {
    const file = loadFile()
    const payload = file.entries[key]
    if (payload === undefined) return { ok: false, error: 'missing' }
    return { ok: true, value: decrypt(payload) }
  } catch (e) {
    return { ok: false, error: `get_failed:${e instanceof Error ? e.message : String(e)}` }
  }
}

export function deleteSecret(key: string): SecretResult {
  if (!isValidKey(key)) return { ok: false, error: 'invalid_key' }
  try {
    const file = loadFile()
    if (!(key in file.entries)) return { ok: false, error: 'missing' }
    delete file.entries[key]
    saveFile(file)
    return { ok: true }
  } catch (e) {
    return { ok: false, error: `delete_failed:${e instanceof Error ? e.message : String(e)}` }
  }
}

export function listSecrets(): { ok: true; keys: string[] } | { ok: false; error: string } {
  try {
    const file = loadFile()
    return { ok: true, keys: Object.keys(file.entries) }
  } catch (e) {
    return { ok: false, error: `list_failed:${e instanceof Error ? e.message : String(e)}` }
  }
}