import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { UIMessageChunk } from 'ai'
import { useAiSdkChatRound } from './useAiSdkChatRound'
import { stepsFromAiParts, type AgentStepView } from '@/utils/agentStepChain'
import type { PlannerSseEvent } from '@/utils/chatSseStream'
import { createXcagiChatTransport } from './xcagiChatTransport'

const { sendChatStream, resumeChatStream } = vi.hoisted(() => ({ sendChatStream: vi.fn(), resumeChatStream: vi.fn() }))

vi.mock('@/api/chat', () => ({
  default: { sendChatStream, resumeChatStream },
  parseChatStreamErrorResponse: vi.fn(async () => '流式请求失败'),
}))

function sseResponse(events: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const text = events.map((event) => `data: ${event}\n\n`).join('')
      controller.enqueue(new TextEncoder().encode(text))
      controller.close()
    },
  })
  return { ok: true, status: 200, body } as unknown as Response
}

async function drain(stream: ReadableStream<UIMessageChunk>): Promise<UIMessageChunk[]> {
  const chunks: UIMessageChunk[] = []
  const reader = stream.getReader()
  while (true) {
    const { done, value } = await reader.read()
    if (done) return chunks
    chunks.push(value)
  }
}

describe('xcagiChatTransport trace event', () => {
  beforeEach(() => {
    sendChatStream.mockReset()
  })

  it('把 trace 条目归一化后交给 onTrace，且不影响正文文本', async () => {
    const onTrace = vi.fn()
    sendChatStream.mockResolvedValueOnce(
      sseResponse([
        JSON.stringify({
          type: 'trace',
          items: [
            { tool: 'read_slice', args: { artifact_id: 'a1', sheet: 'Sheet1' }, ok: true, ms: 12, summary: '读取 3 行' },
            { tool: 'list_attachments', ok: false, ms: '9' },
            { tool: '', ok: true, ms: 1 },
          ],
          turn_id: 'turn-1',
        }),
        JSON.stringify({ type: 'token', text: '你好' }),
      ]),
    )
    const transport = createXcagiChatTransport({ onTrace })

    const chunks = await drain(await transport.sendMessages({ body: { message: 'hi' } }))

    expect(onTrace).toHaveBeenCalledTimes(1)
    expect(onTrace.mock.calls[0][0]).toEqual([
      { tool: 'read_slice', args: { artifact_id: 'a1', sheet: 'Sheet1' }, ok: true, ms: 12, summary: '读取 3 行' },
      { tool: 'list_attachments', ok: false, ms: 9 },
    ])
    expect(chunks).toContainEqual({ type: 'text-delta', id: 'text-1', delta: '你好' })
    expect(chunks.filter((chunk) => chunk.type === 'text-delta')).toHaveLength(1)
  })

  it('空 items 不触发 onTrace；未传 onTrace 也保持兼容', async () => {
    const onTrace = vi.fn()
    sendChatStream
      .mockResolvedValueOnce(sseResponse([JSON.stringify({ type: 'trace', items: [] })]))
      .mockResolvedValueOnce(sseResponse([JSON.stringify({ type: 'trace', items: [{ tool: 'x', ok: true, ms: 1 }] })]))
    const withCallback = createXcagiChatTransport({ onTrace })

    await drain(await withCallback.sendMessages({ body: {} }))
    expect(onTrace).not.toHaveBeenCalled()

    const legacy = createXcagiChatTransport({})
    await expect(drain(await legacy.sendMessages({ body: {} }))).resolves.toBeInstanceOf(Array)
  })
})


describe('native AI SDK tool stream', () => {
  it('resumes at the original opaque SSE cursor and keeps the consumed text only once', async () => {
    const response = (rows: [string, PlannerSseEvent][]) => new Response(rows.map(([id, event]) => `id: ${id}\ndata: ${JSON.stringify(event)}\n\n`).join(''))
    sendChatStream.mockResolvedValueOnce(response([['1700000000000-1', { type: 'token', text: '甲' }]]))
    resumeChatStream.mockResolvedValueOnce(response([
      ['1700000000000-1', { type: 'token', text: '甲' }],
      ['1700000000000-2', { type: 'token', text: '甲' }],
      ['1700000000000-3', { type: 'done', result: { success: true } }],
    ]))
    const round = useAiSdkChatRound({})
    const first = await round.send({ context: { turn_id: 'original-turn' } })
    expect(first.text).toBe('甲')
    expect(first.error).not.toBeNull()
    const result = await round.resume('original-turn')
    expect(resumeChatStream).toHaveBeenLastCalledWith('original-turn', undefined, '1700000000000-1')
    expect(result).toMatchObject({ text: '甲甲', error: null })
  })

  it('renders both tools and updates an earlier parallel tool before the result arrives', async () => {
    let writer!: ReadableStreamDefaultController<Uint8Array>
    const body = new ReadableStream<Uint8Array>({ start(controller) { writer = controller } })
    sendChatStream.mockResolvedValueOnce({ ok: true, body } as Response)
    const emit = (event: PlannerSseEvent) => writer.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`))
    let steps: AgentStepView[] = []
    let settled = false
    const round = useAiSdkChatRound({ onMessage: message => { steps = stepsFromAiParts(message.parts) } })
    const result = round.send({ message: '导入文件' }).finally(() => { settled = true })
    emit({ type: 'tool_call', phase: 'started', node_id: 'import', tool_id: 'elt_import', action: 'preview' })
    emit({ type: 'tool_call', phase: 'started', node_id: 'lookup', tool_id: 'crm', action: 'query' })
    await vi.waitFor(() => expect(steps.map(step => step.state)).toEqual(['running', 'running']))
    emit({ type: 'tool_call', phase: 'progress', node_id: 'import', tool_id: 'elt_import', label: '校验销售明细', progress: 35, processed_rows: 7, total_rows: 20 })
    await vi.waitFor(() => expect(steps[0]).toMatchObject({ id: 'import', action: 'preview', hint: '校验销售明细', progress: 35, processedRows: 7, totalRows: 20 }))
    expect(settled).toBe(false)
    expect(round.text.value).toBe('')
    emit({ type: 'tool_call', phase: 'finished', node_id: 'lookup', success: true, output_preview: '2 个客户' })
    emit({ type: 'tool_call', phase: 'finished', node_id: 'import', success: false, error: '缺少数量字段', recovery_hint: '补充数量后继续', duration_ms: 400,
      trace_id: 'trace-a', span_id: 'span-import', run_id: 'run-a', error_code: 'validation_failed', error_type: 'ValueError' })
    emit({ type: 'token', text: '请补充数量字段。' })
    emit({ type: 'done', result: { success: false } })
    writer.close()
    expect(await result).toMatchObject({ text: '请补充数量字段。', error: null, aborted: false })
    expect(steps).toHaveLength(2)
    expect(steps[0]).toMatchObject({ state: 'failed', error: '缺少数量字段', hint: '补充数量后继续', durationMs: 400,
      trace_id: 'trace-a', span_id: 'span-import', run_id: 'run-a', error_code: 'validation_failed', error_type: 'ValueError' })
    expect(steps[1]).toMatchObject({ state: 'success', output: '2 个客户' })
  })

  it('lets the SDK replace a retried tool and supports receipt-only replay', async () => {
    const events: PlannerSseEvent[] = [
      { type: 'tool_call', phase: 'finished', node_id: 'n1', tool_id: 'excel', action: 'read', success: false, error: '暂时失败' },
      { type: 'tool_call', phase: 'started', node_id: 'n1', tool_id: 'excel', action: 'read', retries: 1,
        trace_id: 'trace-a', span_id: 'span-retry', run_id: 'run-a', attempt: 2 },
      { type: 'tool_call', phase: 'finished', node_id: 'n1', success: true, output_preview: '20 行', retries: 1 },
      { type: 'done' },
    ]
    sendChatStream.mockResolvedValueOnce(sseResponse(events.map(event => JSON.stringify(event))))
    let steps: AgentStepView[] = []
    const result = await useAiSdkChatRound({ onMessage: message => { steps = stepsFromAiParts(message.parts) } }).send({})
    expect(result.error).toBeNull()
    expect(steps).toHaveLength(1)
    expect(steps[0]).toMatchObject({ state: 'success', error: undefined, retries: 1, output: '20 行',
      trace_id: 'trace-a', span_id: 'span-retry', run_id: 'run-a', attempt: 2 })
  })

  it('distinguishes deferred ELT receipts, confirmed writes and unknown side effects', async () => {
    const events: PlannerSseEvent[] = [
      { type: 'tool_call', phase: 'progress', node_id: 'link', tool_id: 'elt_import', label: '正在预演客户及产品' },
      { type: 'tool_call', phase: 'finished', node_id: 'link', success: false, deferred: true,
        output_preview: '客户及产品预演尚未就绪，尚未提交写入', error: '旧版等待信息' },
      { type: 'tool_call', phase: 'finished', node_id: 'some-written', tool_id: 'elt_import', success: false,
        deferred: true, committed: true, output_preview: '运单已写入，客户及产品未提交写入' },
      { type: 'tool_call', phase: 'finished', node_id: 'companion-failed', tool_id: 'elt_import', success: false,
        committed: true, output_preview: '运单已写入', error: '客户及产品处理失败' },
      { type: 'tool_call', phase: 'finished', node_id: 'unknown', tool_id: 'elt_import', success: false,
        committed: true, requires_reconciliation: true, error: '请核对客户及产品回执' },
      { type: 'done', result: { success: false } },
    ]
    sendChatStream.mockResolvedValueOnce(sseResponse(events.map(event => JSON.stringify(event))))
    let steps: AgentStepView[] = []
    const result = await useAiSdkChatRound({ onMessage: message => { steps = stepsFromAiParts(message.parts) } }).send({})

    expect(result.error).toBeNull()
    expect(steps).toMatchObject([
      { state: 'deferred', output: '客户及产品预演尚未就绪，尚未提交写入', error: undefined },
      { state: 'partial', output: '运单已写入，客户及产品未提交写入', error: undefined },
      { state: 'partial', output: '运单已写入', error: '客户及产品处理失败' },
      { state: 'unknown', error: '请核对客户及产品回执' },
    ])
  })
})
