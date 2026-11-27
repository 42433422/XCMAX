import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref, type EffectScope } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import chatApi from '@/api/chat'
import type { ChatPlannerPayload } from '@/types/chat'
import type { UiChatMessage } from '@/types/chat-ui'
import { resolveChatIdentity } from '@/utils/chatStorageKeys'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { pendingRuntimeRunId, runtimeContinuationFromPayload, isRuntimeWaiting } from '@/utils/chatRuntimeContinuation'
import { chatMessageExtrasFromServerRow, resetChatMessageStores, useChatMessages } from './useChatMessages'
import { persistDetachedPlannerResult } from './useChatSessionActivity'
import { useChatRequest } from './useChatRequest'
import { useChatResponseAttach } from './useChatResponseAttach'

vi.mock('@/api/chat', () => ({ default: {
  sendUnifiedChat: vi.fn().mockResolvedValue({ success: true }),
  sendUnifiedChatBatch: vi.fn().mockResolvedValue({ success: true }),
  getConversation: vi.fn().mockResolvedValue({ success: true, messages: [] }),
  saveMessage: vi.fn().mockResolvedValue({ success: true, saved: true, durable: true, message_id: 7 }),
} }))
vi.mock('@/utils/tts', () => ({ speakText: vi.fn(), stopSpeaking: vi.fn(), cleanTextForSpeech: (text: string) => text }))

const waiting: ChatPlannerPayload = {
  success: false, response: '请补充客户名称', runtime: 'xiaox', run_id: 'parent-1',
  execution_state: 'waiting_user', needs_user_input: true,
  runtime_context_update: { agent_runtime_run_id: 'parent-1', conversation_id: 'room-1' },
}
const pointer = { runId: 'parent-1', status: 'waiting_user', sessionId: 'room-1' }
const scopes: EffectScope[] = []

function setupChat() {
  const scope = effectScope()
  scopes.push(scope)
  return scope.run(() => {
    const sessionId = ref('room-1')
    const chat = useChatMessages(sessionId)
    const request = useChatRequest({
      messages: chat.messages, sessionId,
      lastRequestContextSummary: ref(''),
      injectExcelContextPayload: () => false,
      consumeMultimodalIntoPlannerContext: () => {},
      captureArtifacts: () => ({ ids: [], uploadIds: [], complete: () => {} }),
    })
    return { chat, request, sessionId }
  })!
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetChatMessageStores()
  setActivePinia(createPinia())
  setRuntimeTenantStorageScopeInput({ tenantId: 9, localUserId: 1, accountKind: 'enterprise' })
})
afterEach(() => {
  for (const scope of scopes.splice(0)) scope.stop()
  resetChatMessageStores()
  setRuntimeTenantStorageScopeInput(null)
})

describe('runtime continuation through message history and chat requests', () => {
  it('keeps the original waiting run across the Xiaox runtime label migration', () => {
    const migrated = { ...waiting, runtime: 'xiaox', data: { runtime: 'xiaox' } }
    expect(runtimeContinuationFromPayload(migrated)).toEqual(pointer)
    expect(isRuntimeWaiting(migrated)).toBe(true)
    expect(runtimeContinuationFromPayload({ ...waiting, runtime: 'unknown', data: { runtime: 'xiaox' } })).toBeUndefined()
    expect(isRuntimeWaiting({ ...migrated, execution_state: 'queued' })).toBe(false)
  })

  it('restores the server waiting message, survives local reload and sends only the parent hint', async () => {
    const first = setupChat()
    const extras = chatMessageExtrasFromServerRow({ role: 'assistant', id: 7, metadata: { ui: { runtimeContinuation: pointer } } })
    first.chat.loadMessages([{ role: 'ai', content: '请补充客户名称', time: '', ...extras }])
    first.chat.flushMessagesCache()
    scopes.pop()!.stop()
    resetChatMessageStores()
    const { chat, request } = setupChat()
    expect(chat.messages.value.at(-1)?.runtimeContinuation).toEqual(pointer)
    await request.requestChatByMode('客户甲')
    expect(chatApi.sendUnifiedChat).toHaveBeenCalledWith(expect.objectContaining({
      context: expect.objectContaining({ agent_runtime_run_id: 'parent-1', conversation_id: 'room-1' }),
    }), expect.any(Object))
    const context = vi.mocked(chatApi.sendUnifiedChat).mock.calls[0][0].context as Record<string, unknown>
    expect(context).not.toHaveProperty('approval_grant')
    expect(context).not.toHaveProperty('approved')
  })

  it('keeps waiting approval as a continuation hint without converting ordinary confirmation to a grant', () => {
    const { chat, request } = setupChat()
    chat.loadMessages([{ role: 'ai', content: '等待审批', time: '', runtimeContinuation: { ...pointer, status: 'waiting_approval' } }])
    const { body } = request.buildPlannerChatRequestPayload('确认')
    expect(body.context).toMatchObject({ agent_runtime_run_id: 'parent-1' })
    expect(body.context).not.toHaveProperty('approval_grant')
    expect(body.context).not.toHaveProperty('auto_approve')
    expect(body.context).not.toHaveProperty('expected_workflow_plan_id')
  })

  it.each(['terminal', 'unrelated'])('does not revive an older waiting task after a %s reply', kind => {
    const { chat, request } = setupChat()
    const terminal = runtimeContinuationFromPayload({ ...waiting, execution_state: 'reply_completed',
      business_completed: false, runtime_context_update: { agent_runtime_run_id: null, conversation_id: 'room-1' } })
    chat.loadMessages([
      { role: 'ai', content: 'waiting', time: '', runtimeContinuation: pointer },
      { role: 'user', content: 'answer', time: '' },
      { role: 'ai', content: 'reply', time: '', ...(kind === 'terminal' ? { runtimeContinuation: terminal } : {}) },
    ])
    expect(request.buildPlannerChatRequestPayload('新任务').body.context).not.toHaveProperty('agent_runtime_run_id')
    expect(chat.messages.value.at(-1)?.businessResult).toBeUndefined()
    if (kind === 'terminal') expect(chat.messages.value.at(-1)?.runtimeContinuation?.runId).toBeNull()
  })

  it('retains an explicitly preserved parent after admission fails and keeps the failed round state', async () => {
    const blocked = { ...waiting, execution_state: 'blocked', message: 'runtime_not_qualified',
      runtime_context_update: { agent_runtime_run_id: 'parent-1', conversation_id: 'room-1', status: 'waiting_user' } }
    const { chat, request } = setupChat()
    const continuation = runtimeContinuationFromPayload(blocked)
    chat.loadMessages([{ role: 'ai', content: '暂不可运行', time: '', runtimeContinuation: continuation }])
    expect(continuation).toEqual(pointer)
    expect(request.buildPlannerChatRequestPayload('继续').body.context).toHaveProperty('agent_runtime_run_id', 'parent-1')
    const save = vi.fn().mockResolvedValue(undefined)
    await persistDetachedPlannerResult(blocked, 'room-1', save)
    expect(save).toHaveBeenCalledWith('ai', '处理失败: runtime_not_qualified', 'room-1', expect.objectContaining({
      runtimeContinuation: pointer, workflowAction: 'blocked',
    }))
    expect(runtimeContinuationFromPayload({ ...blocked,
      runtime_context_update: { agent_runtime_run_id: null, conversation_id: 'room-1' } })?.runId).toBeNull()
  })

  it('isolates conversations and refuses a stale account scope even if the session name matches', () => {
    const { chat, request, sessionId } = setupChat()
    chat.loadMessages([{ role: 'ai', content: 'waiting', time: '', runtimeContinuation: pointer }])
    const old = { sessionId: 'room-1', messages: [...chat.messages.value], identity: resolveChatIdentity() }
    sessionId.value = 'room-2'
    expect(request.buildPlannerChatRequestPayload('new').body.context).not.toHaveProperty('agent_runtime_run_id')
    expect(request.buildPlannerChatRequestPayload('answer', undefined, old).body.context).toHaveProperty('agent_runtime_run_id', 'parent-1')
    setRuntimeTenantStorageScopeInput({ tenantId: 9, localUserId: 2, accountKind: 'enterprise' })
    expect(request.buildPlannerChatRequestPayload('answer', undefined, old).body.context).not.toHaveProperty('agent_runtime_run_id')
  })

  it('carries the waiting parent on a batch in the same original session', async () => {
    const { chat, request } = setupChat()
    chat.loadMessages([{ role: 'ai', content: 'waiting', time: '', runtimeContinuation: pointer }])
    await request.requestChatByModeBatch(['客户甲', '数量二'])
    expect(chatApi.sendUnifiedChatBatch).toHaveBeenCalledWith(expect.objectContaining({
      context: expect.objectContaining({ agent_runtime_run_id: 'parent-1' }),
    }), expect.any(Object))
  })

  it('ignores user-supplied pointers and a current stream shell while selecting the original wait', () => {
    const rows: UiChatMessage[] = [
      { role: 'ai', content: 'waiting', time: '', runtimeContinuation: pointer },
      { role: 'user', content: 'answer', time: '', runtimeContinuation: { ...pointer, runId: 'forged' } },
      { role: 'ai', content: '', time: '', streamingShell: true },
    ]
    expect(pendingRuntimeRunId(rows, 'room-1')).toBe('parent-1')
    expect(pendingRuntimeRunId(rows, 'room-2')).toBeUndefined()
    expect(chatMessageExtrasFromServerRow({ role: 'user', metadata: { ui: { runtimeContinuation: pointer } } }).runtimeContinuation).toBeUndefined()
  })

  it('sends an independent turn after restoring a legacy unknown receipt', async () => {
    const { chat, request } = setupChat()
    const extras = chatMessageExtrasFromServerRow({
      role: 'assistant', id: 7, metadata: {
        summary: { status: 'unknown', success: false, run_id: 'parent-1' },
        ui: { runtimeContinuation: pointer, execution: { effect: 'unknown', outcome: 'unknown' } },
      },
    })
    chat.loadMessages([{ role: 'ai', content: '请核对原计量回执', time: '', ...extras }])
    expect(pendingRuntimeRunId(chat.messages.value, 'room-1')).toBeUndefined()
    await request.requestChatByMode('解释另一个概念')
    const context = vi.mocked(chatApi.sendUnifiedChat).mock.calls[0][0].context
    expect(context).toMatchObject({ conversation_id: 'room-1', turn_id: expect.any(String) })
    expect(context).not.toHaveProperty('agent_runtime_run_id')
    expect(context).not.toHaveProperty('retry_of')
    expect(chat.messages.value[0]).toMatchObject({ serverMessageId: 7, workflowAction: 'unknown' })
  })

  it('persists an inactive conversation wait and its child approval without a failure prefix', async () => {
    const save = vi.fn().mockResolvedValue(undefined)
    await persistDetachedPlannerResult({ ...waiting, execution_state: 'waiting_approval', data: {
      action: 'approval_pending', data: { approval_card: { run_id: 'child-1', approval_required: true } },
    } }, 'room-1', save)
    expect(save).toHaveBeenCalledWith('ai', '请补充客户名称', 'room-1', expect.objectContaining({
      runtimeContinuation: { ...pointer, status: 'waiting_approval' },
      approvalCard: expect.objectContaining({ run_id: 'child-1' }),
    }))
  })

  it('keeps a detached server wait in the local message before a server history refresh', async () => {
    const { chat, request, sessionId } = setupChat()
    sessionId.value = 'room-2'
    await nextTick()
    await persistDetachedPlannerResult(waiting, 'room-1', chat.saveMessage)
    expect(pendingRuntimeRunId(chat.messages.value, 'room-2')).toBeUndefined()
    sessionId.value = 'room-1'
    await nextTick()
    expect(chat.messages.value.at(-1)?.runtimeContinuation).toEqual(pointer)
    expect(request.buildPlannerChatRequestPayload('客户甲').body.context).toHaveProperty('agent_runtime_run_id', 'parent-1')
  })

  it('keeps the canonical unknown state when attaching or saving a runtime wait', async () => {
    const { chat } = setupChat()
    chat.loadMessages([{ role: 'ai', content: '请核对原回执', time: '' }])
    const payload = { ...waiting, data: { reconciliation_required: true } }
    const attach = useChatResponseAttach({
      messages: chat.messages, lastRequestContextSummary: ref(''), taskList: ref([]),
      upsertTask: vi.fn(), createTaskId: prefix => prefix,
    })
    attach.attachWorkflowTraceToLastAiMessage(payload)
    expect(chat.messages.value.at(-1)).toMatchObject({ workflowAction: 'unknown', runtimeContinuation: pointer })
    const save = vi.fn().mockResolvedValue(undefined)
    await persistDetachedPlannerResult(payload, 'room-1', save)
    expect(save).toHaveBeenCalledWith('ai', '请补充客户名称', 'room-1', expect.objectContaining({
      workflowAction: 'unknown', runtimeContinuation: pointer,
    }))
  })
})
