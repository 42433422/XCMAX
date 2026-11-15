import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  addChatArtifactIds,
  clearChatArtifactIds,
  listChatArtifactIds,
  uploadChatArtifacts,
} from './chatArtifactContext'

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }))

vi.mock('@/utils/apiBase', () => ({ apiFetch }))

function jsonResponse(body: unknown, ok = true): Response {
  return { ok, status: ok ? 200 : 500, json: async () => body } as unknown as Response
}

describe('chatArtifactContext', () => {
  beforeEach(() => {
    clearChatArtifactIds()
    apiFetch.mockReset()
  })

  it('收集去重后的工件 id，发送成功后清空', () => {
    addChatArtifactIds([' a1 ', 'a1', '', 'a2'])
    expect(listChatArtifactIds()).toEqual(['a1', 'a2'])
    clearChatArtifactIds()
    expect(listChatArtifactIds()).toEqual([])
  })

  it('上传时只收集 status=ok 的 artifact.id', async () => {
    apiFetch.mockResolvedValueOnce(jsonResponse({
      ok: true,
      results: [
        { status: 'ok', artifact: { id: 'art-1' } },
        { status: 'skipped', name: '~$a.xlsx' },
        { status: 'ok', artifact: { id: 'art-2' } },
      ],
    }))

    const ids = await uploadChatArtifacts([new File(['x'], 'a.xlsx')])

    expect(apiFetch).toHaveBeenCalledWith('/api/attachments/', expect.objectContaining({ method: 'POST' }))
    expect(ids).toEqual(['art-1', 'art-2'])
    expect(listChatArtifactIds()).toEqual(['art-1', 'art-2'])
  })

  it('上传失败静默，不抛出也不收集', async () => {
    apiFetch.mockRejectedValueOnce(new Error('network down'))

    await expect(uploadChatArtifacts([new File(['x'], 'a.pdf')])).resolves.toEqual([])
    expect(listChatArtifactIds()).toEqual([])
    await expect(uploadChatArtifacts([])).resolves.toEqual([])
  })
})
