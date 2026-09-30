import { beforeEach, describe, expect, it, vi } from 'vitest'

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }))
vi.mock('@/utils/apiBase', () => ({ apiFetch }))

import { aiModBriefFromChat, generateAndInstallAiMod } from './aiModDeliveryApi'

const jsonResponse = (body: unknown, status = 200): Response => Response.json(body, { status })

describe('aiModDeliveryApi', () => {
  beforeEach(() => apiFetch.mockReset())

  it('only intercepts explicit requests to create a self-use module or workflow', () => {
    expect(aiModBriefFromChat('帮我做一个请假审批流')).toBe('帮我做一个请假审批流')
    expect(aiModBriefFromChat('生成一个库存 MOD')).toBe('生成一个库存 MOD')
    expect(aiModBriefFromChat('请假审批流是什么')).toBe('')
    expect(aiModBriefFromChat('请创建一份验收文本文件。审批后实际生成文件并返回真实文件路径。不要修改应用安装目录。')).toBe('')
    expect(aiModBriefFromChat('不要创建应用，请导出工具执行记录')).toBe('')
    expect(aiModBriefFromChat('审批流帮我创建')).toBe('审批流帮我创建')
  })

  it('runs generate, validate and install as one user flow', async () => {
    apiFetch
      .mockResolvedValueOnce(jsonResponse({ success: true, data: { session_id: 'sess-1', status: 'running' } }))
      .mockResolvedValueOnce(
        jsonResponse({ success: true, data: { status: 'running', steps: [{ status: 'running', message: '生成画布' }] } }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ success: true, data: { status: 'done', artifact: { mod_id: 'leave-approval' }, steps: [] } }),
      )
      .mockResolvedValueOnce(jsonResponse({ success: true, message: '安装并激活成功', data: { id: 'leave-approval' } }))
    const progress: string[] = []

    const result = await generateAndInstallAiMod('帮我做一个请假审批流', {
      intervalMs: 10,
      maxRounds: 3,
      onProgress: (row) => progress.push(row.status),
    })

    expect(result.modId).toBe('leave-approval')
    expect(result.installMessage).toBe('安装并激活成功')
    expect(progress).toEqual(['running', 'done'])
    expect(apiFetch).toHaveBeenLastCalledWith('/api/mod-store/ai-delivery/sessions/sess-1/install', { method: 'POST' })
  })

  it('fails closed when workbench validation fails', async () => {
    apiFetch
      .mockResolvedValueOnce(jsonResponse({ success: true, data: { session_id: 'sess-2' } }))
      .mockResolvedValueOnce(jsonResponse({ success: true, data: { status: 'failed', error: '质量校验失败' } }))

    await expect(generateAndInstallAiMod('生成一个销售 MOD', { intervalMs: 10, maxRounds: 1 })).rejects.toThrow('质量校验失败')
    expect(apiFetch).toHaveBeenCalledTimes(2)
  })
})
