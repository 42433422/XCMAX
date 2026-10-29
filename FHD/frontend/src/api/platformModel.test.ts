import { beforeEach, describe, expect, it, vi } from 'vitest'
import { platformModelApi, type PlatformModelDraft } from './platformModel'
import { api } from './core'

vi.mock('./core', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }))
const path = '/api/xcmax/market-proxy/llm/admin/platform-model-config'
const draft: PlatformModelDraft = { base_url: 'https://models.example.com/v1', model: 'example-model', display_name: '测试模型', make_default: true, expected_revision: null }

beforeEach(() => vi.clearAllMocks())
describe('platform model API', () => {
  it('uses the authenticated proxy and disables browser caching for the masked configuration read', async () => {
    const signal = new AbortController().signal
    await platformModelApi.list(signal)
    expect(api.get).toHaveBeenCalledWith(path, {}, { signal, timeoutMs: 15_000, cache: 'no-store' })
  })
  it('writes the credential only in a PUT body and preserves omitted keys on metadata edits', async () => {
    await platformModelApi.save('openai', draft)
    expect(api.put).toHaveBeenCalledWith(`${path}/openai`, draft, { signal: undefined, timeoutMs: 20_000 })
    const body = { ...draft, api_key: 'example-not-real-api-key' }
    await platformModelApi.save('openai', body)
    expect(api.put).toHaveBeenLastCalledWith(`${path}/openai`, body, expect.any(Object))
    expect(vi.mocked(api.put).mock.calls.every(call => !call[0].includes('example-not-real-api-key'))).toBe(true)
  })
  it('uses a separate bounded test request and safely encodes the provider path', async () => {
    const signal = new AbortController().signal
    await platformModelApi.test('provider/path', draft, signal)
    expect(api.post).toHaveBeenCalledWith(`${path}/provider%2Fpath/test`, draft, { signal, timeoutMs: 35_000 })
    expect(api.put).not.toHaveBeenCalled()
  })
})
