import { describe, it, expect, beforeEach, vi } from 'vitest'

const apiFetchMock = vi.fn()
vi.mock('@/utils/apiBase', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}))

import { streamSuperEmployeeMessage } from './superEmployeeStream'

function sseResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder()
  let i = 0
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i >= chunks.length) {
        controller.close()
        return
      }
      controller.enqueue(encoder.encode(chunks[i]))
      i += 1
    },
  })
  return new Response(stream, {
    status,
    headers: { 'content-type': 'text/event-stream' },
  })
}

function jsonErrorResponse(body: unknown, status = 500): Response {
  return {
    ok: false,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
    body: null,
  } as Response
}

describe('streamSuperEmployeeMessage', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
  })

  it('posts to admin stream endpoint by default and assembles tokens', async () => {
    const tokens: string[] = []
    const statuses: string[] = []
    apiFetchMock.mockResolvedValue(
      sseResponse([
        'data: {"type":"status","text":"thinking"}\n\n',
        'data: {"type":"token","text":"你"}\n\n',
        'data: {"type":"token","text":"好"}\n\n',
        'data: {"type":"done","result":{"response":"你好世界"}}\n\n',
      ]),
    )

    const result = await streamSuperEmployeeMessage(
      'codex',
      'ping',
      { source: 'admin_im' },
      {
        onToken: (t) => tokens.push(t),
        onStatus: (t) => statuses.push(t),
      },
    )

    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/admin/codex-super-employee/messages/stream',
      expect.objectContaining({
        method: 'POST',
        timeoutMs: 0,
        body: JSON.stringify({
          message: 'ping',
          workspace_id: 'xcmax',
          context: { source: 'admin_im', workspace_id: 'xcmax' },
        }),
      }),
    )
    expect(tokens).toEqual(['你', '好'])
    expect(statuses).toEqual(['thinking'])
    expect(result).toBe('你好世界')
  })

  it('uses mobile scope and workspaceId option', async () => {
    apiFetchMock.mockResolvedValue(
      sseResponse(['data: {"type":"token","text":"ok"}\n\n']),
    )
    await streamSuperEmployeeMessage('trae', 'hi', {}, {
      scope: 'mobile',
      workspaceId: 'ws-1',
    })
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/mobile/v1/admin/trae-super-employee/messages/stream',
      expect.objectContaining({
        body: JSON.stringify({
          message: 'hi',
          workspace_id: 'ws-1',
          context: { workspace_id: 'ws-1' },
        }),
      }),
    )
  })

  it('falls back to assembled tokens when done has no response', async () => {
    apiFetchMock.mockResolvedValue(
      sseResponse([
        'data: {"type":"token","text":"ab"}\n\n',
        'data: {"type":"done"}\n\n',
      ]),
    )
    await expect(streamSuperEmployeeMessage('claude', 'x')).resolves.toBe('ab')
  })

  it('uses done.text when result.response missing', async () => {
    apiFetchMock.mockResolvedValue(
      sseResponse(['data: {"type":"done","text":"from-text"}\n\n']),
    )
    await expect(streamSuperEmployeeMessage('cursor', 'x')).resolves.toBe('from-text')
  })

  it('returns placeholder when stream yields nothing', async () => {
    apiFetchMock.mockResolvedValue(sseResponse(['data: {"type":"status","text":""}\n\n']))
    await expect(streamSuperEmployeeMessage('codex', 'x')).resolves.toBe('（无回复）')
  })

  it('ignores invalid JSON and [DONE] payloads', async () => {
    apiFetchMock.mockResolvedValue(
      sseResponse([
        'data: not-json\n\n',
        'data: [DONE]\n\n',
        'data: {"type":"token","text":"z"}\n\n',
      ]),
    )
    await expect(streamSuperEmployeeMessage('codex', 'x')).resolves.toBe('z')
  })

  it('throws on SSE error event', async () => {
    apiFetchMock.mockResolvedValue(
      sseResponse(['data: {"type":"error","message":"boom"}\n\n']),
    )
    await expect(streamSuperEmployeeMessage('codex', 'x')).rejects.toThrow('boom')
  })

  it('throws default message on error event without message', async () => {
    apiFetchMock.mockResolvedValue(sseResponse(['data: {"type":"error"}\n\n']))
    await expect(streamSuperEmployeeMessage('codex', 'x')).rejects.toThrow('流式调用失败')
  })

  it('throws JSON error body on non-ok response', async () => {
    apiFetchMock.mockResolvedValue(jsonErrorResponse({ message: 'denied' }, 403))
    await expect(streamSuperEmployeeMessage('codex', 'x')).rejects.toThrow('denied')
  })

  it('throws HTTP status when non-ok JSON has no message', async () => {
    apiFetchMock.mockResolvedValue(jsonErrorResponse({}, 502))
    await expect(streamSuperEmployeeMessage('codex', 'x')).rejects.toThrow(
      '流式调用失败（HTTP 502）',
    )
  })

  it('throws HTTP status for non-JSON error response', async () => {
    apiFetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      headers: new Headers({ 'content-type': 'text/plain' }),
      body: null,
    } as Response)
    await expect(streamSuperEmployeeMessage('codex', 'x')).rejects.toThrow(
      '流式调用失败（HTTP 500）',
    )
  })

  it('throws when response body is missing', async () => {
    apiFetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: null,
    } as Response)
    await expect(streamSuperEmployeeMessage('codex', 'x')).rejects.toThrow('流式响应无 body')
  })

  it('handles trailing buffer without final blank line', async () => {
    apiFetchMock.mockResolvedValue(
      sseResponse(['data: {"type":"token","text":"tail"}']),
    )
    await expect(streamSuperEmployeeMessage('codex', 'x')).resolves.toBe('tail')
  })
})
