import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  addChatArtifacts,
  captureChatArtifacts,
  clearChatArtifactIds,
  listChatArtifactIds,
  removeChatArtifactId,
  uploadChatArtifacts,
  uploadChatArtifactsDetailed,
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
    addChatArtifacts([' a1 ', 'a1', '', 'a2'].map(id => ({ id })))
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

  it('保留服务器返回的上传标识和对应的芯片展示名', async () => {
    apiFetch.mockResolvedValueOnce(jsonResponse({
      results: [
        { status: 'skipped', name: '~$a.xlsx' },
        { status: 'ok', artifact: { id: 'art-1', elt_upload_id: 'upload-1' } },
      ],
    }))

    const rows = await uploadChatArtifactsDetailed([
      new File(['x'], '~$a.xlsx'), new File(['y'], '销售明细.xlsx'),
    ])

    expect(rows).toEqual([{ id: 'art-1', name: '销售明细.xlsx', uploadId: 'upload-1' }])
    expect(captureChatArtifacts()).toMatchObject({ ids: ['art-1'], uploadIds: ['upload-1'] })
  })

  it('移除芯片时同步移除待发送工件 id', () => {
    addChatArtifacts([{ id: 'a1', uploadId: 'upload-1' }, { id: 'a2', uploadId: 'upload-2' }])
    removeChatArtifactId(' a1 ')
    removeChatArtifactId('')
    expect(captureChatArtifacts()).toMatchObject({ ids: ['a2'], uploadIds: ['upload-2'] })
  })

  it('上一轮已发出后重新上传，只保留本轮文件', () => {
    addChatArtifacts([{ id: 'old-1', uploadId: 'upload-1' }, { id: 'old-2', uploadId: 'upload-2' }])
    captureChatArtifacts()
    addChatArtifacts(['new-1', 'new-2', 'new-3'].map(id => ({ id })))
    expect(listChatArtifactIds()).toEqual(['new-1', 'new-2', 'new-3'])
  })

  it('非重试的新消息丢弃上一轮残留', () => {
    addChatArtifacts([{ id: 'old', uploadId: 'upload-1' }])
    captureChatArtifacts()
    expect(captureChatArtifacts()).toMatchObject({ ids: [], uploadIds: [] })
  })
})
