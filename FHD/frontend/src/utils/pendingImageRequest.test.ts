import { webcrypto } from 'node:crypto'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { finishImageRequest, reserveImageRequest } from './pendingImageRequest'

describe('pending image request receipts', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.stubGlobal('crypto', webcrypto)
  })

  it('reuses a pending key after reload and separates owner, chat, mod and prompt', async () => {
    const original = await reserveImageRequest('user:1', 'chat-1', 'mod-1', '同一个提示词')
    const afterReload = await reserveImageRequest('user:1', 'chat-1', 'mod-1', '同一个提示词')
    expect(afterReload).toEqual(original)
    expect(original.key).not.toContain('同一个提示词')
    for (const args of [
      ['user:2', 'chat-1', 'mod-1', '同一个提示词'],
      ['user:1', 'chat-2', 'mod-1', '同一个提示词'],
      ['user:1', 'chat-1', 'mod-2', '同一个提示词'],
      ['user:1', 'chat-1', 'mod-1', '另一个提示词'],
    ]) {
      const other = await reserveImageRequest(args[0], args[1], args[2], args[3])
      expect(other.requestId).not.toBe(original.requestId)
    }
    finishImageRequest(original.key, 'different')
    expect(localStorage.getItem(original.key)).toBe(original.requestId)
    finishImageRequest(original.key, original.requestId)
    expect(localStorage.getItem(original.key)).toBeNull()
  })

  it('does not submit from an unresolved account or replace corrupt records', async () => {
    await expect(reserveImageRequest('local', 'chat', '', 'prompt')).rejects.toThrow()
    const original = await reserveImageRequest('user:1', 'chat', '', 'prompt')
    localStorage.setItem(original.key, 'corrupt')
    await expect(reserveImageRequest('user:1', 'chat', '', 'prompt')).rejects.toThrow()
    expect(localStorage.getItem(original.key)).toBe('corrupt')
  })
})
