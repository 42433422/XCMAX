import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readFleet, submitControlTask } from './macControl'

const fetchMock = vi.hoisted(() => vi.fn())
vi.mock('@/utils/apiBase', () => ({ apiFetch: fetchMock }))

describe('Mac control management contract', () => {
  beforeEach(() => fetchMock.mockReset())
  it('keeps the request identity on retries through the existing employee endpoint', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ success: true, task: { id: 'same-task' } }) })
    await submitControlTask('inspect', 'stable-key', 'mac', 'review')
    await submitControlTask('inspect', 'stable-key', 'mac', 'review')
    expect(fetchMock.mock.calls[0]).toEqual(fetchMock.mock.calls[1])
    expect(fetchMock.mock.calls[0][0]).toBe('/api/admin/codex-super-employee/messages')
    const payload = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(payload.durable_request.request_key).toBe('stable-key')
    expect(payload.durable_request.auto_merge).toBeUndefined()
  })
  it('does not show an authentication failure as an empty healthy fleet', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 401, json: async () => ({ detail: 'login required' }) })
    await expect(readFleet()).rejects.toThrow('login required')
  })
})
