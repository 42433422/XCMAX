import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  addChatArtifactIds,
  clearChatArtifactIds,
  listChatArtifactIds,
  markChatArtifactsConsumed,
  removeChatArtifactId,
  takeChatArtifactIds,
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

  it('详细上传返回芯片展示名，缺名时回退到文件名', async () => {
    apiFetch.mockResolvedValueOnce(jsonResponse({
      results: [{ status: 'ok', artifact: { id: 'art-1', name: '销售明细.xlsx' } }],
    }))

    const rows = await uploadChatArtifactsDetailed([
      new File(['x'], 'a.xlsx'),
      new File(['y'], 'b.xlsx'),
    ])

    expect(rows).toEqual([{ id: 'art-1', name: '销售明细.xlsx' }])
    expect(listChatArtifactIds()).toEqual(['art-1'])
  })

  it('移除芯片时同步移除待发送工件 id', () => {
    addChatArtifactIds(['a1', 'a2'])
    removeChatArtifactId(' a1 ')
    removeChatArtifactId('')
    expect(listChatArtifactIds()).toEqual(['a2'])
  })

  it('上一轮已发出后重新上传，只保留本轮文件', () => {
    addChatArtifactIds(['old-1', 'old-2'])
    takeChatArtifactIds()
    markChatArtifactsConsumed()

    addChatArtifactIds(['new-1', 'new-2', 'new-3'])

    expect(listChatArtifactIds()).toEqual(['new-1', 'new-2', 'new-3'])
  })

  it('失败重试沿用上一轮已提交的工件', () => {
    addChatArtifactIds(['a1'])
    takeChatArtifactIds()
    markChatArtifactsConsumed()

    expect(takeChatArtifactIds({ retry: true })).toEqual(['a1'])
  })

  it('非重试的新消息丢弃上一轮残留', () => {
    addChatArtifactIds(['old'])
    takeChatArtifactIds()
    markChatArtifactsConsumed()

    expect(takeChatArtifactIds()).toEqual([])
    expect(listChatArtifactIds()).toEqual([])
  })
})
