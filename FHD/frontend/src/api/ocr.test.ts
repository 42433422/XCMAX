import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ocrApi } from './ocr'

vi.mock('./core', () => ({
  api: {
    post: vi.fn().mockResolvedValue({ success: true, data: {} }),
  },
}))

describe('ocrApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('recognizeText calls POST /api/ocr/recognize', async () => {
    const data = { image: 'base64...' }
    await ocrApi.recognizeText(data)
    const { api } = await import('./core')
    expect(api.post).toHaveBeenCalledWith('/api/ocr/recognize', data)
  })

  it('extractStructured calls POST /api/ocr/extract', async () => {
    const data = { text: 'sample' }
    await ocrApi.extractStructured(data)
    const { api } = await import('./core')
    expect(api.post).toHaveBeenCalledWith('/api/ocr/extract', data)
  })

  it('analyzeText calls POST /api/ocr/analyze', async () => {
    const data = { text: 'sample' }
    await ocrApi.analyzeText(data)
    const { api } = await import('./core')
    expect(api.post).toHaveBeenCalledWith('/api/ocr/analyze', data)
  })

  it('recognizeAndExtract calls POST /api/ocr/recognize-and-extract', async () => {
    const data = { image: 'base64...' }
    await ocrApi.recognizeAndExtract(data)
    const { api } = await import('./core')
    expect(api.post).toHaveBeenCalledWith('/api/ocr/recognize-and-extract', data)
  })
})
