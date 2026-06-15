import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mediaApi } from './media'

vi.mock('./core', () => ({
  api: {
    post: vi.fn().mockResolvedValue({ success: true, data: {} }),
    get: vi.fn().mockResolvedValue({ success: true, data: [] }),
    download: vi.fn().mockResolvedValue(new Response()),
  },
}))

describe('mediaApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('uploadFile calls POST /api/media/upload', async () => {
    const formData = new FormData()
    await mediaApi.uploadFile(formData)
    const { api } = await import('./core')
    expect(api.post).toHaveBeenCalledWith('/api/media/upload', formData)
  })

  it('getImages calls GET /api/media/images', async () => {
    await mediaApi.getImages()
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/media/images')
  })

  it('getVideos calls GET /api/media/videos', async () => {
    await mediaApi.getVideos()
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/media/videos')
  })

  it('downloadFile calls download with url', async () => {
    await mediaApi.downloadFile('/api/media/file/1')
    const { api } = await import('./core')
    expect(api.download).toHaveBeenCalledWith('/api/media/file/1')
  })
})
