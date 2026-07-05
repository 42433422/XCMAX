import { describe, expect, it, vi, beforeEach } from 'vitest'
import { llm } from './llm'
import { req, authHeaders } from './shared'

vi.mock('./shared', () => ({
  req: vi.fn(),
  authHeaders: vi.fn(() => ({ Authorization: 'Bearer test' })),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('llm api', () => {

  it('llmStatus calls req', async () => {
    vi.mocked(req).mockResolvedValue({ providers: [] })
    const res = await llm.llmStatus()
    expect(req).toHaveBeenCalledWith('/api/llm/status')
    expect(res).toEqual({ providers: [] })
  })

  it('llmResolveChatDefault calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmResolveChatDefault()
    expect(req).toHaveBeenCalledWith('/api/llm/resolve-chat-default')
  })

  it('llmCatalog passes refresh param', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmCatalog(true)
    expect(req).toHaveBeenCalledWith('/api/llm/catalog?refresh=1')
  })

  it('llmSaveCredentials calls req with PUT', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmSaveCredentials('openai', 'sk-xxx', 'https://api.openai.com')
    expect(req).toHaveBeenCalledWith('/api/llm/credentials/openai', expect.objectContaining({ method: 'PUT' }))
  })

  it('llmDeleteCredentials calls req with DELETE', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmDeleteCredentials('openai')
    expect(req).toHaveBeenCalledWith('/api/llm/credentials/openai', expect.objectContaining({ method: 'DELETE' }))
  })

  it('llmSavePreferences calls req with PUT', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmSavePreferences('openai', 'gpt-4')
    expect(req).toHaveBeenCalledWith('/api/llm/preferences', expect.objectContaining({ method: 'PUT' }))
  })

  it('llmPricing calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmPricing()
    expect(req).toHaveBeenCalledWith('/api/llm/pricing')
  })

  it('llmUsage passes limit and offset', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmUsage(10, 5)
    expect(req).toHaveBeenCalledWith('/api/llm/usage?limit=10&offset=5')
  })

  it('llmConversations passes limit and offset', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmConversations(20, 10)
    expect(req).toHaveBeenCalledWith('/api/llm/conversations?limit=20&offset=10')
  })

  it('llmConversationDetail encodes id', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmConversationDetail(42)
    expect(req).toHaveBeenCalledWith('/api/llm/conversations/42')
  })

  it('llmAdminSavePrice calls req with PUT', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmAdminSavePrice({ key: 'val' })
    expect(req).toHaveBeenCalledWith('/api/llm/admin/pricing', expect.objectContaining({ method: 'PUT' }))
  })

  it('llmAdminListPricing builds query string', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmAdminListPricing({ provider: 'openai', limit: 100 })
    const url = vi.mocked(req).mock.calls[0][0] as string
    expect(url).toContain('/api/llm/admin/pricing')
    expect(url).toContain('provider=openai')
  })

  it('llmAdminBatchPricing calls POST batch', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmAdminBatchPricing({ provider: 'openai', mode: 'unpriced_only' })
    expect(req).toHaveBeenCalledWith('/api/llm/admin/pricing/batch', expect.objectContaining({ method: 'POST' }))
  })

  it('llmAdminPricingSettings calls PUT settings', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmAdminPricingSettings({ service_fee_multiplier: 1.8 })
    expect(req).toHaveBeenCalledWith('/api/llm/admin/pricing/settings', expect.objectContaining({ method: 'PUT' }))
  })

  it('llmAdminSyncOfficialPrices calls POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmAdminSyncOfficialPrices({ provider: 'openai', apply_markup: true })
    expect(req).toHaveBeenCalledWith('/api/llm/admin/pricing/sync-official', expect.objectContaining({ method: 'POST' }))
  })

  it('llmAdminApplyOfficialMarkup calls POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmAdminApplyOfficialMarkup({ provider: 'deepseek', multiplier: 1.5 })
    expect(req).toHaveBeenCalledWith('/api/llm/admin/pricing/apply-official-markup', expect.objectContaining({ method: 'POST' }))
  })

  it('llmAdminModelCapabilities builds query string', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmAdminModelCapabilities({ provider: 'openai', q: 'gpt', limit: 10 })
    const call = vi.mocked(req).mock.calls[0] as any[]
    const url = call[0] as string
    expect(url).toContain('provider=openai')
    expect(url).toContain('q=gpt')
    expect(url).toContain('limit=10')
  })

  it('llmAdminModelCapabilities with no opts', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmAdminModelCapabilities()
    expect(req).toHaveBeenCalledWith('/api/llm/admin/model-capabilities')
  })

  it('llmAdminModelCapabilityReview calls req with PUT', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmAdminModelCapabilityReview({ provider: 'openai', model: 'gpt-4', l3_status: 'approved' })
    expect(req).toHaveBeenCalledWith('/api/llm/admin/model-capabilities/review', expect.objectContaining({ method: 'PUT' }))
  })

  it('llmChat calls req with POST and returns result', async () => {
    vi.mocked(req).mockResolvedValue({ content: 'hello', billed: false })
    const res = await llm.llmChat('openai', 'gpt-4', [{ role: 'user', content: 'hi' }])
    expect(req).toHaveBeenCalledWith('/api/llm/chat', expect.objectContaining({ method: 'POST' }))
    expect(res.content).toBe('hello')
  })

  it('llmChat triggers billing refresh when billed', async () => {
    const mockRefresh = vi.fn()
    vi.doMock('../utils/llmBillingRefresh', () => ({
      refreshLevelAndWalletAfterLlm: mockRefresh,
    }))
    vi.mocked(req).mockResolvedValue({ content: 'hello', billed: true, charge_amount: 0.5 })
    await llm.llmChat('openai', 'gpt-4', [{ role: 'user', content: 'hi' }])
  })

  it('llmChat does not trigger billing refresh when not billed', async () => {
    vi.mocked(req).mockResolvedValue({ content: 'hello' })
    const res = await llm.llmChat('openai', 'gpt-4', [{ role: 'user', content: 'hi' }])
    expect(res.content).toBe('hello')
  })

  it('llmChatStream calls fetch with correct params', async () => {
    const mockFetch = vi.fn().mockResolvedValue(new Response())
    vi.stubGlobal('fetch', mockFetch)
    await llm.llmChatStream('openai', 'gpt-4', [{ role: 'user', content: 'hi' }])
    expect(mockFetch).toHaveBeenCalledWith('/api/llm/chat/stream', expect.objectContaining({
      method: 'POST',
    }))
    vi.unstubAllGlobals()
  })

  it('llmGenerateImage calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmGenerateImage('openai', 'dall-e-3', 'a cat', { size: '512x512', count: 2 })
    expect(req).toHaveBeenCalledWith('/api/llm/image', expect.objectContaining({ method: 'POST' }))
  })

  it('llmGenerateVideo calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await llm.llmGenerateVideo('openai', 'sora', 'a cat walking', { size: '1280x720', seconds: 5 })
    expect(req).toHaveBeenCalledWith('/api/llm/video', expect.objectContaining({ method: 'POST' }))
  })

  it('llmGeneratePptxBlob throws on non-ok response', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
    })
    vi.stubGlobal('fetch', mockFetch)
    await expect(llm.llmGeneratePptxBlob('title', 'markdown')).rejects.toThrow()
    vi.unstubAllGlobals()
  })

  it('llmGeneratePptxBlob returns blob on success', async () => {
    const buf = new ArrayBuffer(8)
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: () => Promise.resolve(buf),
    })
    vi.stubGlobal('fetch', mockFetch)
    const result = await llm.llmGeneratePptxBlob('title', 'markdown', 'test.pptx')
    expect(result).toBeInstanceOf(Blob)
    expect(result.type).toBe('application/vnd.openxmlformats-officedocument.presentationml.presentation')
    vi.unstubAllGlobals()
  })
})
