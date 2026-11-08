import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useKittenChatSend, type KittenChatSendDeps } from './useKittenChatSend'

const boundary = vi.hoisted(() => ({ stream: vi.fn(), getRun: vi.fn(), json: vi.fn(), streaming: true }))
vi.mock('@/api/chat', () => ({ chatApi: { sendChatStream: boundary.stream }, parseChatStreamErrorResponse: async () => '请求被拒绝' }))
vi.mock('@/api/agentRuns', () => ({ agentRunsApi: { getRun: boundary.getRun } }))
vi.mock('@/utils/safeJsonRequest', () => ({ safeJsonRequest: boundary.json }))
vi.mock('@/utils/chatSseStream', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  isChatStreamEnabled: () => boundary.streaming,
}))

const sse = (...events: Record<string, unknown>[]) =>
  new Response(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } })
function setup() {
  const deps: KittenChatSendDeps = {
    messages: ref([]),
    inputText: ref('创建客户并返回结果'),
    isChatLoading: ref(false),
    isKittenStreaming: ref(false),
    isDatasetParsing: ref(false),
    kittenPhase: ref('idle'),
    currentResult: ref(null),
    kittenSessionUserId: ref('kitten-session'),
    kittenIncludeBusinessDb: ref(false),
    kittenIncludeWebSearch: ref(true),
    datasetSummary: ref(null),
    lastWebSearchHits: ref([]),
    addMessage(role, content) {
      deps.messages.value.push({ role, content, time: '' })
    },
    scrollChatToBottom: vi.fn(),
  }
  return { deps, ...useKittenChatSend(deps) }
}
const started = { type: 'tool_progress', phase: 'started', run_id: 'original-run' }
const token = { type: 'token', text: '已开始创建，请等待。' }

describe('Kitten execution receipts', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    boundary.streaming = true
  })

  it('keeps visible output and reads only the original run after an incomplete stream', async () => {
    boundary.stream.mockResolvedValue(sse(started, token))
    boundary.getRun.mockRejectedValue(new Error('lookup unavailable'))
    const { deps, sendMessage } = setup()
    await sendMessage()
    expect(boundary.getRun).toHaveBeenCalledExactlyOnceWith('original-run')
    expect(boundary.stream).toHaveBeenCalledTimes(1)
    expect(boundary.json).not.toHaveBeenCalled()
    expect(deps.messages.value.at(-1)?.content).toContain('已开始创建')
    expect(deps.messages.value.at(-1)?.content).toContain('勿重复提交')
    expect(deps.kittenPhase.value).toBe('unknown')
    expect(deps.currentResult.value?.execution).toMatchObject({ run_id: 'original-run', status: 'unknown' })
  })

  it.each(['network', 'error_event', 'incomplete'])('does not guess a run or retry when %s returns no run id', async (failure) => {
    if (failure === 'network') boundary.stream.mockRejectedValue(new Error('network lost'))
    else boundary.stream.mockResolvedValue(failure === 'error_event' ? sse(token, { type: 'error', message: '服务器中断' }) : sse(token))
    const { deps, sendMessage } = setup()
    await sendMessage()
    expect(boundary.getRun).not.toHaveBeenCalled()
    expect(boundary.json).not.toHaveBeenCalled()
    expect(deps.kittenPhase.value).toBe('unknown')
  })

  it.each(['DB_READ_TOKEN', 'DB_WRITE_TOKEN', 'API_KEY'])(
    'keeps %s authorization visible and distinct from approval/completion',
    async (tokenName) => {
      boundary.stream.mockResolvedValue(
        sse(started, token, {
          type: 'requires_token',
          token_name: tokenName,
          token_description: '授权后继续',
          run_id: 'original-run',
          approval_id: 'approval-original',
        }),
      )
      const { deps, sendMessage } = setup()
      await sendMessage()
      expect(deps.kittenPhase.value).toBe('waiting_authorization')
      expect(deps.currentResult.value?.execution).toMatchObject({
        run_id: 'original-run',
        approval_id: 'approval-original',
        token_name: tokenName,
      })
      expect(deps.messages.value.at(-1)?.content).toContain('需要授权')
      expect(boundary.json).not.toHaveBeenCalled()
    },
  )

  it('does not let a transport done success override a pending authorization', async () => {
    boundary.stream.mockResolvedValue(
      sse({ type: 'requires_token', token_name: 'DB_WRITE_TOKEN' }, { type: 'done', result: { success: true, response: '已接收' } }),
    )
    const { deps, sendMessage } = setup()
    await sendMessage()
    expect(deps.kittenPhase.value).toBe('waiting_authorization')
  })

  it.each(['running', 'queued', 'waiting_approval', 'waiting_user', 'unknown'])(
    'reads %s as an unfinished business state even with query success',
    async (status) => {
      boundary.stream.mockResolvedValue(sse(started, token))
      boundary.getRun.mockResolvedValue({
        success: true,
        data: {
          run_id: 'original-run',
          status,
          final_output: { chat_payload: { success: true, response: '仍在处理', approval_id: 'approval-original' } },
        },
      })
      const { deps, sendMessage } = setup()
      await sendMessage()
      expect(deps.kittenPhase.value).not.toBe('delivered')
      expect(deps.currentResult.value?.execution?.run_id).toBe('original-run')
      expect(boundary.json).not.toHaveBeenCalled()
      if (status === 'waiting_approval') expect(deps.currentResult.value?.execution?.approval_id).toBe('approval-original')
    },
  )

  it('reads the original run from an HTTP stream error without replaying the request', async () => {
    boundary.stream.mockResolvedValue(new Response(JSON.stringify({ data: { agent_run_id: 'original-run' } }), { status: 503 }))
    boundary.getRun.mockResolvedValue({
      success: true,
      data: { run_id: 'original-run', status: 'running', final_output: { chat_payload: { success: false, response: '原任务仍在处理' } } },
    })
    const { deps, sendMessage } = setup()
    await sendMessage()
    expect(boundary.getRun).toHaveBeenCalledExactlyOnceWith('original-run')
    expect(boundary.json).not.toHaveBeenCalled()
    expect(deps.kittenPhase.value).toBe('analyzing')
    expect(deps.currentResult.value?.execution?.status).toBe('running')
  })

  it('uses the persisted original chat result after a completed run is read back', async () => {
    boundary.stream.mockResolvedValue(sse(started, token))
    boundary.getRun.mockResolvedValue({
      success: true,
      data: {
        run_id: 'original-run',
        status: 'completed',
        final_output: { chat_payload: { success: true, response: '客户已创建，记录ID 17' } },
      },
    })
    const { deps, sendMessage } = setup()
    await sendMessage()
    expect(deps.kittenPhase.value).toBe('delivered')
    expect(deps.messages.value.at(-1)?.content).toContain('记录ID 17')
    expect(boundary.json).not.toHaveBeenCalled()
  })

  it.each(['wrong_run', 'wrong_turn', 'missing_payload', 'unknown_effect'])('refuses unverified completion from %s', async (problem) => {
    boundary.stream.mockResolvedValue(sse(started, token))
    boundary.getRun.mockResolvedValue({
      success: true,
      data: {
        run_id: problem === 'wrong_run' ? 'other-run' : 'original-run',
        status: 'completed',
        metadata: problem === 'wrong_turn' ? { task_context: { turn_id: 'other-turn' } } : {},
        final_output:
          problem === 'missing_payload'
            ? {}
            : { chat_payload: { success: true, response: '不应显示', reconciliation_required: problem === 'unknown_effect' } },
      },
    })
    const { deps, sendMessage } = setup()
    await sendMessage()
    expect(deps.kittenPhase.value).toBe('unknown')
    expect(deps.messages.value.at(-1)?.content).not.toContain('不应显示')
  })

  it.each([
    [{ success: true, result: { output: { pending_approval: true } } }, 'waiting_approval'],
    [{ success: true, outputs: [{ requires_token: true, token_name: 'DB_READ_TOKEN' }] }, 'waiting_authorization'],
    [{ success: true, outputs: { write: { success: false, message: '写入失败' } } }, 'error'],
    [{ success: true, result: { output: { status: 'unrecognized_state' } } }, 'unknown'],
    [{ success: true, result: { output: { execution_state: 'unknown' } } }, 'unknown'],
    [{ success: true, result: { state: 'waiting_auth' } }, 'waiting_authorization'],
    [{ success: true, output: { execution_status: 'awaiting_approval' } }, 'waiting_approval'],
    [{ success: true, result: { needs_user_input: true } }, 'waiting_user'],
    [{ success: true, output: { ok: false, message: '业务失败' } }, 'error'],
    [{ success: true, outputs: [{ error: '工具失败' }] }, 'error'],
    [{ success: true, result: { exit_status: 'partial_success' } }, 'unknown'],
    [{}, 'unknown'],
  ])('checks nested execution receipts and rejects empty completion: %s', async (result, expectedPhase) => {
    boundary.stream.mockResolvedValue(sse(token, { type: 'done', result }))
    const { deps, sendMessage } = setup()
    await sendMessage()
    expect(deps.kittenPhase.value).toBe(expectedPhase)
    expect(deps.messages.value.at(-1)?.content).toContain('已开始创建')
    expect(boundary.json).not.toHaveBeenCalled()
  })

  it('retains an explicit timed_out error receipt instead of declaring completion', async () => {
    const status = 'timed_out'
    boundary.stream.mockResolvedValue(sse({ type: 'done', result: { success: true, result: { status } } }))
    const { deps, sendMessage } = setup()
    await sendMessage()
    expect(deps.kittenPhase.value).toBe('error')
    expect(deps.currentResult.value?.execution?.status).toBe(status)
  })

  it.each(['interrupted', 'partial', 'partial_success', 'partial_failure'])(
    'keeps %s unconfirmed ahead of approval or success',
    async (status) => {
      boundary.stream.mockResolvedValue(sse(token, { type: 'done', result: { success: true, pending_approval: true, result: { status } } }))
      const { deps, sendMessage } = setup()
      await sendMessage()
      expect(deps.kittenPhase.value).toBe('unknown')
      expect(deps.currentResult.value?.execution?.status).toBe('unknown')
      expect(deps.messages.value.at(-1)?.content).toContain('已开始创建')
      expect(deps.messages.value.at(-1)?.content).toContain('勿重复提交')
      expect(boundary.json).not.toHaveBeenCalled()
    },
  )

  it('recovers a nested run reference and preserves the original approval reference', async () => {
    boundary.stream.mockResolvedValue(sse({ type: 'tool_progress', data: { agent_run_id: 'original-run' } }, token))
    boundary.getRun.mockResolvedValue({
      success: true,
      data: {
        run_id: 'original-run',
        status: 'waiting_approval',
        final_output: { chat_payload: { success: true, result: { pending_approval: true, approval: { id: 'approval-original' } } } },
      },
    })
    const { deps, sendMessage } = setup()
    await sendMessage()
    expect(boundary.getRun).toHaveBeenCalledExactlyOnceWith('original-run')
    expect(deps.kittenPhase.value).toBe('waiting_approval')
    expect(deps.currentResult.value?.execution?.approval_id).toBe('approval-original')
  })

  it('does not let a completed query status override the saved authorization pause', async () => {
    boundary.stream.mockResolvedValue(sse(started, token))
    boundary.getRun.mockResolvedValue({
      success: true,
      data: {
        run_id: 'original-run',
        status: 'completed',
        final_output: { chat_payload: { success: true, result: { requires_token: true, token_name: 'API_KEY' } } },
      },
    })
    const { deps, sendMessage } = setup()
    await sendMessage()
    expect(deps.kittenPhase.value).toBe('waiting_authorization')
    expect(boundary.json).not.toHaveBeenCalled()
  })

  it('freezes history, dataset, switches and turn identity before awaiting a response', async () => {
    let release!: (response: Response) => void
    boundary.stream.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve
        }),
    )
    const { deps, sendMessage } = setup()
    deps.messages.value.push({ role: 'user', content: '原历史', time: '' })
    deps.datasetSummary.value = { name: '原件.xlsx', rows: 2, columns: 1, fieldNames: ['名称'], previewText: '原内容' }
    const pending = sendMessage()
    const payload = boundary.stream.mock.calls[0][0]
    deps.datasetSummary.value.name = '新文件.xlsx'
    deps.datasetSummary.value.fieldNames[0] = '改列'
    deps.kittenIncludeWebSearch.value = false
    deps.messages.value[0].content = '改历史'
    expect(payload.context).toMatchObject({
      kitten_web_search: true,
      recent_messages: [{ role: 'user', content: '原历史' }],
      kitten_dataset: { name: '原件.xlsx', fields: ['名称'] },
    })
    expect(payload.context.turn_id).toMatch(/^turn_/)
    expect(payload.context.task_id).toMatch(/^task_/)
    release(sse({ type: 'done', result: { success: true, response: '完成' } }))
    await pending
    expect(deps.currentResult.value?.execution?.turn_id).toBe(payload.context.turn_id)
    expect(deps.kittenPhase.value).toBe('delivered')
  })

  it('does not replace a newly reset session with an old response', async () => {
    let release!: (response: Response) => void
    boundary.stream.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve
        }),
    )
    const { deps, sendMessage } = setup()
    const pending = sendMessage()
    deps.kittenSessionUserId.value = 'new-session'
    deps.messages.value = []
    deps.kittenPhase.value = 'idle'
    release(sse({ type: 'done', result: { success: true, response: '旧回复' } }))
    await pending
    expect(deps.messages.value).toEqual([])
    expect(deps.kittenPhase.value).toBe('idle')
    expect(deps.currentResult.value).toBeNull()
  })

  it.each([
    [{ success: true, response: 'JSON完成' }, 'delivered'],
    [
      { success: true, response: '待授权', requires_token: true, token_name: 'DB_READ_TOKEN', run_id: 'original-run' },
      'waiting_authorization',
    ],
    [{ success: true, response: '待审批', execution_state: 'waiting_approval', approval_id: 'approval-original' }, 'waiting_approval'],
    [{ success: true, response: '执行结果不明', tool_records: [{ output: { outcome: 'unknown' } }] }, 'unknown'],
    [{ success: false, response: '执行失败' }, 'error'],
  ])('supports explicit JSON with business state %s', async (data, expectedPhase) => {
    boundary.streaming = false
    boundary.json.mockResolvedValue({ ok: true, status: 200, data, message: '' })
    const { deps, sendMessage } = setup()
    await sendMessage()
    expect(boundary.stream).not.toHaveBeenCalled()
    expect(boundary.json).toHaveBeenCalledTimes(1)
    expect(deps.kittenPhase.value).toBe(expectedPhase)
    const body = JSON.parse(boundary.json.mock.calls[0][1].body)
    expect(body.context.turn_id).toBe(deps.currentResult.value?.execution?.turn_id)
  })
})
