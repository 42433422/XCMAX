import { describe, expect, it, vi } from 'vitest'
import { postClientDebugLog } from './clientDebugLog'

vi.mock('./apiBase', () => ({
  apiFetch: vi.fn().mockResolvedValue({ status: 200 }),
}))

describe('clientDebugLog', () => {
  it('queues payload without throwing when bridge enabled', () => {
    localStorage.setItem('xcagi_client_debug_log', '1')
    expect(() => postClientDebugLog({ message: 'test' })).not.toThrow()
  })

  it('no-ops when bridge disabled', () => {
    localStorage.setItem('xcagi_client_debug_log', '0')
    expect(() => postClientDebugLog({ message: 'x' })).not.toThrow()
  })
})
