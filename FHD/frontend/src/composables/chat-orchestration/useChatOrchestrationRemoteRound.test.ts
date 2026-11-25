/**
 * useChatOrchestrationRemoteRound 行为测试。
 *
 * 直接在边界处替换 chatApi / productsApi / SSE 读取器，驱动真实的
 * executeRemoteChatRound：请求载荷、流式事件顺序、授权暂停、断线续传、
 * 归属失效、非流式回退与批量分支。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref, watch } from 'vue'
import type { UiChatMessage } from '@/types/chat-ui'
import type { PlannerSseEvent } from '@/utils/chatSseStream'
import type { ChatRequestScope } from '../useChatRequest'
import { useChatSessionActivity } from '../useChatSessionActivity'
import { useChatOrchestrationRemoteRound } from './useChatOrchestrationRemoteRound'

type SseScript = (emit: (event: PlannerSseEvent) => void, signal?: AbortSignal) => Promise<void>

const h = vi.hoisted(() => {
  const state = {
    streamEnabled: true,
    authOk: true,
    adminConsole: false,
    activeModId: '',
    productKeyword: null as string | null,
    sseScript: null as SseScript | null,
  }
  const readPlannerSseResponse = vi.fn(async (_response: unknown, onEvent: (event: PlannerSseEvent) => void, signal?: AbortSignal) => {
    await state.sseScript?.(onEvent, signal)
  })
  return {
    state,
    readPlannerSseResponse,
    sendChatStream: vi.fn(),
    resumeChatStream: vi.fn(),
    getConversation: vi.fn(),
    parseChatStreamErrorResponse: vi.fn(async () => '流式请求失败'),
    searchProducts: vi.fn(),
    generateAndInstallAiMod: vi.fn(),
    probeEnterpriseSession: vi.fn(),
    recordProductFastPathTask: vi.fn(async () => undefined),
    persistDetachedPlannerResult: vi.fn(async () => undefined),
  }
})

vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({ activeModId: h.state.activeModId, mods: [], modsForUi: [], setActiveModId: vi.fn() }),
}))
vi.mock('@/utils/chatStorageKeys', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/chatStorageKeys')>()),
  resolveChatIdentity: (modId?: string) => `identity:${String(modId ?? '')}`,
}))
vi.mock('@/api/chat', () => ({
  default: { sendChatStream: h.sendChatStream, resumeChatStream: h.resumeChatStream, getConversation: h.getConversation },
  parseChatStreamErrorResponse: h.parseChatStreamErrorResponse,
}))
vi.mock('@/api/products', () => ({ default: { searchProducts: h.searchProducts } }))
vi.mock('@/utils/aiModDeliveryApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/aiModDeliveryApi')>()),
  aiModBriefFromChat: (text: string) => (text.startsWith('MOD:') ? text.slice(4) : ''),
  generateAndInstallAiMod: h.generateAndInstallAiMod,
}))
vi.mock('@/utils/authSessionCache', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/authSessionCache')>()),
  captureAuthSession: () => () => h.state.authOk,
  probeEnterpriseSession: h.probeEnterpriseSession,
}))
vi.mock('@/utils/adminConsoleUrl', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/adminConsoleUrl')>()),
  isAdminConsoleSpa: () => h.state.adminConsole,
}))
vi.mock('../useChatPersistence', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../useChatPersistence')>()),
  extractLikelyProductQueryKeyword: () => h.state.productKeyword,
}))
vi.mock('../useChatSessionActivity', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../useChatSessionActivity')>()),
  recordProductFastPathTask: h.recordProductFastPathTask,
  persistDetachedPlannerResult: h.persistDetachedPlannerResult,
}))
vi.mock('@/utils/chatSseStream', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/chatSseStream')>()),
  isChatStreamEnabled: () => h.state.streamEnabled,
  readPlannerSseResponse: h.readPlannerSseResponse,
}))

function feed(events: PlannerSseEvent[]) {
  h.state.sseScript = async (emit) => {
    for (const event of events) emit(event)
  }
}

function scope(overrides: Partial<ChatRequestScope> = {}): ChatRequestScope {
  return { sessionId: 'session-1', messages: [], isCurrent: () => true, turnId: 'turn-1', ...overrides }
}

type StateStep = { node_id: string; status: 'succeeded' | 'failed'; output_summary: string }

function setup(options: { tts?: boolean; multimodal?: number; excelContext?: boolean } = {}) {
  const sessionId = ref('session-1')
  const messages = ref<UiChatMessage[]>([])
  const stateSteps = ref<StateStep[]>([])
  const currentTask = ref<unknown>({ type: 'existing' })
  const ttsEnabled = ref(options.tts ?? true)
  const multimodalPendingCount = ref(options.multimodal ?? 0)
  const resolveExcelAnalysisContextForRequest = vi.fn(() => (options.excelContext ? { file_path: 'x.xlsx' } : null))

  const addMessage = vi.fn((content: string, role: 'user' | 'ai' | 'task' = 'ai', extras?: Partial<UiChatMessage>) => {
    messages.value.push({ role, content, time: '', ...(extras || {}) })
  })
  const applyPlainTextToMessageIndex = vi.fn((index: number, text: string, extras?: Partial<UiChatMessage>) => {
    const row = messages.value[index]
    if (!row) return
    row.content = text
    if (extras) Object.assign(row, extras)
    if (text) delete row.streamingShell
    else row.streamingShell = true
  })
  const pushStreamingAiShell = vi.fn(() => {
    messages.value.push({ role: 'ai', content: '', time: '', streamingShell: true })
    return messages.value.length - 1
  })
  const saveMessage = vi.fn(async () => undefined)
  const queueVoice = vi.fn()
  const flushMessagesCache = vi.fn()

  const chatRequest = {
    setLoadingProgress: vi.fn(),
    startWaitProgressTimer: vi.fn(),
    buildPlannerChatRequestPayload: vi.fn((message: string, _opts?: unknown, requestScope?: ChatRequestScope) => ({
      body: { message, context: { turn_id: requestScope?.turnId || '', session_id: requestScope?.sessionId || '' } },
      completeArtifacts: vi.fn(),
    })),
    stopLoadingProgress: vi.fn(),
    requestChatByModeWithTimeout: vi.fn(),
    requestChatByModeBatchWithTimeout: vi.fn(),
    resolveChatTimeoutMs: vi.fn(() => 30_000),
  }

  const deps = {
    sessionId,
    messages,
    addMessage,
    saveMessage,
    queueVoice,
    pushStreamingAiShell,
    applyPlainTextToMessageIndex,
    flushMessagesCache,
    ttsEnabled,
    chatSessionActivity: useChatSessionActivity(sessionId),
    chatRequest,
    resolveExcelAnalysisContextForRequest,
    multimodalPendingCount,
    stateSteps,
    currentTask,
    syncTaskFromChatResponse: vi.fn(),
    attachThinkingStepsToLastAiMessage: vi.fn(),
    attachTodoStepsToLastAiMessage: vi.fn(),
    attachWorkflowTraceToLastAiMessage: vi.fn(),
    attachApprovalCardToLastAiMessage: vi.fn(),
    attachBusinessResultToLastAiMessage: vi.fn(),
    attachAgentRunTraceToLastAiMessage: vi.fn(),
    attachContextSummaryToLastAiMessage: vi.fn(),
    syncAgentRunFromPayload: vi.fn(async () => undefined),
    observeActiveTurn: vi.fn(),
    showTaskConfirm: vi.fn(),
    maybeCloseAssistantFloatForShipmentTask: vi.fn(),
    emitAssistantPush: vi.fn(),
    handleAutoAction: vi.fn(),
  }
  const round = useChatOrchestrationRemoteRound(deps as unknown as Parameters<typeof useChatOrchestrationRemoteRound>[0])

  const appliedTexts = () => applyPlainTextToMessageIndex.mock.calls.map((call) => call[1] as string)
  const progressTexts = () => chatRequest.setLoadingProgress.mock.calls.map((call) => call[0] as string)

  return { sessionId, messages, stateSteps, currentTask, ttsEnabled, deps, round, appliedTexts, progressTexts }
}

function routePayload() {
  return { provider: 'platform', model: 'gpt-x', route_source: 'platform', key_source: 'managed', route_state: 'completed', config_revision: 'r1' }
}

function captureTimers() {
  const scheduled: Array<{ cb: () => void; ms: number }> = []
  const realSetTimeout = window.setTimeout.bind(window)
  const spy = vi.spyOn(window, 'setTimeout').mockImplementation(((cb: TimerHandler, ms?: number) => {
    scheduled.push({ cb: cb as () => void, ms: Number(ms ?? 0) })
    return realSetTimeout(cb as () => void, ms) as unknown as number
  }) as typeof window.setTimeout)
  return { scheduled, restore: () => spy.mockRestore() }
}

beforeEach(() => {
  vi.clearAllMocks()
  h.state.streamEnabled = true
  h.state.authOk = true
  h.state.adminConsole = false
  h.state.activeModId = ''
  h.state.productKeyword = null
  h.state.sseScript = null
  h.sendChatStream.mockResolvedValue({ ok: true, status: 200, body: {} })
  h.resumeChatStream.mockReset().mockResolvedValue({ ok: true, status: 200, body: {} })
  h.getConversation.mockReset()
  h.getConversation.mockRejectedValue(new Error('history unavailable'))
  h.searchProducts.mockResolvedValue({ success: true, data: [], total: 0 })
  h.generateAndInstallAiMod.mockResolvedValue({ modId: 'mod-self-1', installMessage: '已安装到自用 MOD' })
  h.probeEnterpriseSession.mockResolvedValue('invalid')
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('consumeStateUpdates 合并后端步骤进度', () => {
  it('按 node_id 新增或原地更新，忽略非 state.update 与空 node_id', () => {
    const { round, stateSteps } = setup()
    round.consumeStateUpdates({
      data: {
        data: {
          state_updates: [
            { type: 'state.update', node_id: 'n1', status: 'succeeded', output_summary: '第一步' },
            { type: 'state.update', node_id: 'n2', status: 'failed', output_summary: '第二步失败' },
            { type: 'other', node_id: 'n3', status: 'succeeded' },
            { type: 'state.update', status: 'succeeded' },
          ],
        },
      },
    })
    expect(stateSteps.value).toEqual([
      { node_id: 'n1', status: 'succeeded', output_summary: '第一步' },
      { node_id: 'n2', status: 'failed', output_summary: '第二步失败' },
    ])

    round.consumeStateUpdates({ state_updates: [{ type: 'state.update', node_id: 'n1', status: 'failed', output_summary: '重试也失败' }] })
    expect(stateSteps.value).toEqual([
      { node_id: 'n1', status: 'failed', output_summary: '重试也失败' },
      { node_id: 'n2', status: 'failed', output_summary: '第二步失败' },
    ])

    round.consumeStateUpdates({ data: { data: { state_updates: [] } } })
    expect(stateSteps.value).toHaveLength(2)
  })
})

describe('maybePrefetchProductAssistantFloat 产品副窗预开', () => {
  it('识别到产品关键词时派发打开副窗事件', async () => {
    const { round } = setup()
    h.state.productKeyword = '5003A'
    const handler = vi.fn()
    window.addEventListener('xcagi:open-assistant-float', handler)
    round.maybePrefetchProductAssistantFloat('查一下 5003A')
    window.removeEventListener('xcagi:open-assistant-float', handler)
    expect(handler).toHaveBeenCalledTimes(1)
    expect((handler.mock.calls[0][0] as CustomEvent).detail).toEqual({ feature: 'products', query: '5003A', forceOpen: true })
  })

  it('没有关键词时不派发事件', () => {
    const { round } = setup()
    const handler = vi.fn()
    window.addEventListener('xcagi:open-assistant-float', handler)
    round.maybePrefetchProductAssistantFloat('今天天气如何')
    window.removeEventListener('xcagi:open-assistant-float', handler)
    expect(handler).not.toHaveBeenCalled()
  })
})

describe('executeRemoteChatRound 产品快路径', () => {
  it('命中产品库时写回执、记录任务并注入副窗数据', async () => {
    const { round, deps, messages, currentTask } = setup()
    h.state.productKeyword = '5003A'
    h.searchProducts.mockResolvedValue({
      success: true,
      total: 5,
      data: [
        { id: 1, model_number: '5003A', name: '清漆', price: 120, unit: '桶' },
        { id: 2, model_number: '5003B', name: '底漆', price: 88.5 },
        { id: 3, model_number: '', product_name: '面漆', price: 'bad' },
        { id: 4, model_number: '5003D', name: '固化剂', price: 12 },
      ],
    })

    await round.executeRemoteChatRound(['查 5003A'], undefined, scope())

    expect(h.searchProducts).toHaveBeenCalledWith('5003A')
    expect(h.recordProductFastPathTask).toHaveBeenCalledWith(
      'session-1',
      '查 5003A',
      '5003A',
      expect.arrayContaining([{ id: 1, model_number: '5003A', name: '清漆', price: 120, unit: '桶' }]),
      5,
      expect.stringContaining('预览命中 4 条'),
    )
    expect(deps.saveMessage.mock.calls).toEqual([
      ['user', '查 5003A', 'session-1'],
      ['ai', expect.stringContaining('已帮你打开产品副窗并带入「5003A」'), 'session-1'],
    ])
    expect(deps.handleAutoAction).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'show_products_float', query: '5003A', hydrateProductSearch: expect.objectContaining({ total: 5 }) }),
      '查 5003A',
    )
    expect(deps.syncTaskFromChatResponse).toHaveBeenCalled()
    expect(deps.attachContextSummaryToLastAiMessage).toHaveBeenCalled()
    expect(deps.attachApprovalCardToLastAiMessage).toHaveBeenCalled()
    expect(currentTask.value).toBeNull()
    expect(messages.value[0]?.content).toContain('预览命中')
    expect(deps.chatRequest.requestChatByModeWithTimeout).not.toHaveBeenCalled()
    expect(deps.chatRequest.stopLoadingProgress).toHaveBeenCalledWith('session-1')
  })

  it('产品库无结果时提示确认关键词且不打开副窗', async () => {
    const { round, deps } = setup()
    h.state.productKeyword = '不存在的型号'
    h.searchProducts.mockResolvedValue({ success: true, data: [], total: 0 })

    await round.executeRemoteChatRound(['查不存在的型号'], undefined, scope())

    expect(deps.addMessage).toHaveBeenCalledWith('未在产品库中找到「不存在的型号」，请确认型号或关键词后重试。', 'ai', expect.objectContaining({ turnId: 'turn-1' }), expect.any(Object))
    expect(deps.handleAutoAction).not.toHaveBeenCalled()
  })

  it('产品接口失败时回退到统一聊天链路', async () => {
    h.state.streamEnabled = false
    const { round, deps } = setup()
    h.state.productKeyword = '5003A'
    h.searchProducts.mockResolvedValue({ success: false, message: '产品库维护中' })
    deps.chatRequest.requestChatByModeWithTimeout.mockResolvedValue({ success: true, response: '回退回复' })

    await round.executeRemoteChatRound(['查 5003A'], undefined, scope())

    expect(deps.chatRequest.requestChatByModeWithTimeout).toHaveBeenCalledWith('查 5003A', 30_000, undefined, expect.any(Object))
    expect(deps.addMessage).toHaveBeenCalledWith('回退回复', 'ai', expect.objectContaining({ turnId: 'turn-1' }), expect.any(Object))
  })

  it.each([
    ['多模态待发送', { multimodal: 1 }],
    ['已挂载 Excel 上下文', { excelContext: true }],
  ])('%s 时跳过产品快路径', async (_label, options) => {
    h.state.streamEnabled = false
    const { round, deps } = setup(options)
    h.state.productKeyword = '5003A'
    deps.chatRequest.requestChatByModeWithTimeout.mockResolvedValue({ success: true, response: '普通回复' })

    await round.executeRemoteChatRound(['查 5003A'], undefined, scope())

    expect(h.searchProducts).not.toHaveBeenCalled()
    expect(deps.chatRequest.requestChatByModeWithTimeout).toHaveBeenCalled()
  })

  it('管理端不使用产品快路径', async () => {
    h.state.streamEnabled = false
    const { round, deps } = setup()
    h.state.adminConsole = true
    h.state.productKeyword = '5003A'
    deps.chatRequest.requestChatByModeWithTimeout.mockResolvedValue({ success: true, response: '普通回复' })

    await round.executeRemoteChatRound(['查 5003A'], undefined, scope())

    expect(h.searchProducts).not.toHaveBeenCalled()
    expect(deps.chatRequest.requestChatByModeWithTimeout).toHaveBeenCalled()
  })

  it('产品请求返回前归属失效时静默放弃写回执', async () => {
    const { round, deps } = setup()
    h.state.productKeyword = '5003A'
    h.searchProducts.mockImplementation(async () => {
      h.state.authOk = false
      return { success: true, data: [{ id: 1, model_number: '5003A' }] }
    })

    await round.executeRemoteChatRound(['查 5003A'], undefined, scope())

    expect(deps.addMessage).not.toHaveBeenCalled()
    expect(deps.saveMessage).not.toHaveBeenCalled()
    expect(h.recordProductFastPathTask).not.toHaveBeenCalled()
  })
})

describe('executeRemoteChatRound AI MOD 交付', () => {
  it('生成并安装自用 MOD 后写入带节点结果的消息', async () => {
    const { round, deps } = setup()
    h.generateAndInstallAiMod.mockImplementation(async (_brief: string, options: { onProgress?: (p: { label: string }) => void }) => {
      options.onProgress?.({ label: '正在校验 MOD…' })
      return { modId: 'mod-9', installMessage: '安装完成' }
    })

    await round.executeRemoteChatRound(['MOD:帮我做一个客户管理模块'], undefined, scope())

    expect(h.generateAndInstallAiMod).toHaveBeenCalledWith('帮我做一个客户管理模块', expect.objectContaining({ isCurrent: expect.any(Function), onProgress: expect.any(Function) }))
    expect(h.searchProducts).not.toHaveBeenCalled()
    expect(deps.chatRequest.setLoadingProgress).toHaveBeenCalledWith('正在创建自用 MOD…', 'session-1')
    expect(deps.chatRequest.setLoadingProgress).toHaveBeenCalledWith('正在校验 MOD…', 'session-1')
    expect(deps.addMessage).toHaveBeenCalledWith(
      '已生成并安装自用 MOD「mod-9」。安装完成',
      'ai',
      expect.objectContaining({
        turnId: 'turn-1',
        workflowAction: 'mod_generated_and_installed',
        nodeResults: [
          { node_id: 'generate', tool_id: 'workbench', action: 'generate_mod', success: true },
          { node_id: 'validate', tool_id: 'workbench', action: 'validate_mod', success: true },
          { node_id: 'install', tool_id: 'mod_store', action: 'install_self_use', success: true },
        ],
      }),
      expect.any(Object),
    )
    expect(deps.saveMessage.mock.calls).toEqual([
      ['user', 'MOD:帮我做一个客户管理模块', 'session-1'],
      ['ai', '已生成并安装自用 MOD「mod-9」。安装完成', 'session-1', expect.objectContaining({ workflowAction: 'mod_generated_and_installed' })],
    ])
    expect(deps.chatRequest.stopLoadingProgress).toHaveBeenCalledWith('session-1')
  })

  it('生成失败时把错误写回聊天并保存', async () => {
    const { round, deps } = setup()
    h.generateAndInstallAiMod.mockRejectedValue(new Error('后端生成超时'))

    await round.executeRemoteChatRound(['MOD:做一个审批流模块'], undefined, scope())

    expect(deps.addMessage).toHaveBeenCalledWith('MOD 生成或安装失败：后端生成超时', 'ai', expect.objectContaining({ turnId: 'turn-1' }), expect.any(Object))
    expect(deps.saveMessage).toHaveBeenCalledWith('ai', 'MOD 生成或安装失败：后端生成超时', 'session-1')
  })

  it('安装完成后归属失效时不写任何消息', async () => {
    const { round, deps } = setup()
    h.generateAndInstallAiMod.mockImplementation(async () => {
      h.state.authOk = false
      return { modId: 'mod-x', installMessage: '完成' }
    })

    await round.executeRemoteChatRound(['MOD:做一个客户模块'], undefined, scope())

    expect(deps.addMessage).not.toHaveBeenCalled()
    expect(deps.saveMessage).not.toHaveBeenCalled()
  })
})

describe('executeRemoteChatRound 流式回合', () => {
  it.each([true, false])('模板清理完成后通知已打开的模板库刷新（success=%s）', async (success) => {
    const { round } = setup()
    const updates: unknown[] = []
    const onUpdate = (event: Event) => updates.push((event as CustomEvent).detail)
    window.addEventListener('xcagi:templates-updated', onUpdate)
    feed([
      { type: 'tool_call', phase: 'started', node_id: 'tpl', tool_id: 'document_template', action: 'clear' },
      { type: 'tool_call', phase: 'finished', node_id: 'other', tool_id: 'crm', action: 'create_customer', success: true },
      { type: 'tool_call', phase: 'finished', node_id: 'tpl', tool_id: 'document_template', action: 'clear', success },
      { type: 'done', result: { success, response: '模板清理已结束' } },
    ])
    try {
      await round.executeRemoteChatRound(['清空模板库'], undefined, scope())
      expect(updates).toEqual([{ source: 'chat', action: 'clear' }])
    } finally {
      window.removeEventListener('xcagi:templates-updated', onUpdate)
    }
  })

  it('按事件顺序维护思考、执行链、路线并落终态', async () => {
    const { round, deps, messages, stateSteps, currentTask, appliedTexts } = setup()
    const route = routePayload()
    feed([
      { type: 'route_metadata', route_metadata: route },
      { type: 'thinking', delta: '先查客户' },
      { type: 'thinking', delta: '再建订单' },
      { type: 'tool_progress', text: '正在查询客户', run_id: 'run-1' },
      { type: 'tool_progress', phase: 'started' },
      { type: 'tool_call', phase: 'started', node_id: 'n1', tool_id: 'crm', action: 'create_customer' },
      { type: 'tool_call', phase: 'finished', node_id: 'n1', tool_id: 'crm', action: 'create_customer', success: true },
      { type: 'token', text: '你' },
      { type: 'token', text: '仍在思考', ephemeral: true },
      { type: 'token', text: '好' },
      {
        type: 'done',
        result: {
          success: true,
          response: '你好',
          route_metadata: route,
          task: { type: 'custom', title: '处理客户', description: '请确认客户信息' },
          autoAction: { type: 'show_orders' },
          cached: true,
          execution: { committed: false, effect: 'preview', outcome: 'partial', idempotency_key: 'idem-1', intent: 'create_customer' },
          businessResult: { status: 'completed', summary: '客户已创建', facts: { customer_id: 9 }, evidence: { completed_tool_count: 1 } },
          data: { data: { state_updates: [{ type: 'state.update', node_id: 'n1', status: 'succeeded', output_summary: '客户创建成功' }] } },
        },
      },
    ])

    await round.executeRemoteChatRound(['创建客户'], undefined, scope())

    expect(h.sendChatStream).toHaveBeenCalledWith(expect.objectContaining({ message: '创建客户' }), expect.objectContaining({ signal: expect.anything() }))
    expect(messages.value[0].turnId).toBe('turn-1')
    expect(messages.value[0].thinkingSteps).toBe('先查客户\n再建订单')
    expect(messages.value[0].routeMetadata).toEqual(route)
    expect(messages.value[0].liveSteps).toHaveLength(1)
    expect(messages.value[0].liveSteps?.[0]).toMatchObject({ toolId: 'crm', action: 'create_customer', state: 'success' })
    expect(deps.chatRequest.setLoadingProgress).toHaveBeenCalledWith('正在查询客户', 'session-1')
    expect(deps.chatRequest.setLoadingProgress).toHaveBeenCalledWith('正在执行任务…', 'session-1')
    expect(deps.chatRequest.setLoadingProgress).toHaveBeenCalledWith('正在生成回复…', 'session-1')
    expect(deps.stateSteps).toBeDefined()
    expect(stateSteps.value).toEqual([{ node_id: 'n1', status: 'succeeded', output_summary: '客户创建成功' }])
    expect(appliedTexts().at(-1)).toBe('你好')
    const extras = deps.applyPlainTextToMessageIndex.mock.calls.at(-1)?.[2]
    expect(extras).toMatchObject({
      routeMetadata: route,
      sameAsPrevious: true,
      execution: expect.objectContaining({ committed: false, effect: 'preview' }),
      businessResult: expect.objectContaining({ summary: '客户已创建' }),
    })
    expect(deps.queueVoice).toHaveBeenCalledWith('你好')
    expect(deps.showTaskConfirm).toHaveBeenCalledWith(expect.objectContaining({ title: '处理客户' }))
    expect(deps.emitAssistantPush).toHaveBeenCalledWith({ title: '处理客户', description: '请确认客户信息' })
    expect(deps.handleAutoAction).toHaveBeenCalledWith({ type: 'show_orders' }, '创建客户')
    expect(currentTask.value).toEqual({ type: 'existing' })
    expect(deps.maybeCloseAssistantFloatForShipmentTask).toHaveBeenCalledWith(expect.objectContaining({ title: '处理客户' }), { type: 'show_orders' })
    expect(deps.syncAgentRunFromPayload).toHaveBeenCalledWith(expect.objectContaining({ run_id: 'run-1' }), '创建客户', expect.any(Function))
    expect(deps.flushMessagesCache).toHaveBeenCalled()
    expect(messages.value[0].streamingShell).toBeUndefined()
  })

  it('旧写入授权事件只保留原运行等待回执', async () => {
    const { round, deps, messages } = setup()
    feed([{ type: 'requires_token', token_name: 'DB_WRITE_TOKEN', token_description: '写入数据库', run_id: 'run-w' }])

    await round.executeRemoteChatRound(['导入数据'], undefined, scope())

    expect(deps.showTaskConfirm).not.toHaveBeenCalled()
    expect(deps.handleAutoAction).not.toHaveBeenCalled()
    expect(deps.chatSessionActivity.statuses.value['session-1']).toBe('waiting')
    expect(messages.value[0].content).toBe('\n[需要授权：写入数据库]\n')
    expect(deps.saveMessage).not.toHaveBeenCalled()
    expect(deps.flushMessagesCache).toHaveBeenCalled()
    expect(deps.syncAgentRunFromPayload).toHaveBeenCalledWith(expect.objectContaining({ run_id: 'run-w' }), '导入数据', expect.any(Function))
  })

  it('旧只读授权事件仅显示等待，不执行后续动作', async () => {
    const { round, deps } = setup()
    feed([{ type: 'requires_token', token_name: 'DB_READ_TOKEN', token_description: '读取数据' }])

    await round.executeRemoteChatRound(['查询数据'], undefined, scope())

    expect(deps.showTaskConfirm).not.toHaveBeenCalled()
    expect(deps.handleAutoAction).not.toHaveBeenCalled()
    expect(deps.chatSessionActivity.statuses.value['session-1']).toBe('waiting')
  })

  it('没有完成回执时用历史回执替换失败气泡', async () => {
    const { round, deps, appliedTexts } = setup()
    feed([{ type: 'token', text: '部分输出' }])
    h.getConversation.mockResolvedValue({
      success: true,
      messages: [
        {
          role: 'assistant',
          content: '服务端已完成',
          metadata: { summary: { turn_id: 'turn-1', status: 'completed', success: true } },
        },
      ],
    })

    await round.executeRemoteChatRound(['继续'], undefined, scope())

    expect(h.getConversation).toHaveBeenCalledWith('session-1', { turn_id: 'turn-1' })
    expect(appliedTexts().at(-1)).toBe('服务端已完成')
    expect(deps.showTaskConfirm).not.toHaveBeenCalled()
  })

  it('服务端状态未确认时标记 unknown 并延迟回读补齐', async () => {
    vi.useFakeTimers()
    const { round, messages, appliedTexts } = setup()
    feed([{ type: 'token', text: '半截回复' }])
    h.getConversation
      .mockRejectedValueOnce(new Error('history unavailable'))
      .mockResolvedValueOnce({
        success: true,
        messages: [
          {
            role: 'assistant',
            content: '迟到的完整回复',
            metadata: { summary: { turn_id: 'turn-1', status: 'completed', success: true } },
          },
        ],
      })

    await round.executeRemoteChatRound(['继续'], undefined, scope())

    expect(appliedTexts().at(-1)).toContain('[回复未完成]')
    expect(appliedTexts().at(-1)).toContain('连接中断，结果未知')
    expect(messages.value[0].workflowAction).toBe('unknown')

    await vi.advanceTimersByTimeAsync(1500)
    expect(appliedTexts().at(-1)).toBe('迟到的完整回复')
    expect(messages.value[0].workflowAction).toBe('completed')
  })

  it('流式中途归属失效时中止且不写终态', async () => {
    const { round, deps, messages } = setup()
    h.state.sseScript = async (emit) => {
      emit({ type: 'token', text: '你' })
      h.state.authOk = false
      emit({ type: 'requires_token', token_name: 'DB_WRITE_TOKEN', token_description: '写入数据库' })
    }

    await round.executeRemoteChatRound(['导入'], undefined, scope())

    expect(deps.applyPlainTextToMessageIndex).not.toHaveBeenCalled()
    expect(deps.saveMessage).not.toHaveBeenCalled()
    expect(messages.value[0].streamingShell).toBe(true)
  })

  it('SSE error 事件按未知结果收敛并记录执行失败', async () => {
    const { round, deps, messages, appliedTexts } = setup()
    feed([
      {
        type: 'error',
        message: '模型不可用',
        run_id: 'run-e',
        requires_reconciliation: true,
        result: { execution: { committed: true, effect: 'committed', outcome: 'failed', idempotency_key: 'k-e' } },
      },
    ])

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(appliedTexts().at(-1)).toBe('处理失败：模型不可用')
    expect(deps.applyPlainTextToMessageIndex).toHaveBeenLastCalledWith(0, '处理失败：模型不可用', {
      execution: expect.objectContaining({ committed: true, outcome: 'failed' }),
    })
    expect(messages.value[0].workflowAction).toBe('unknown')
    expect(deps.syncAgentRunFromPayload).toHaveBeenCalledWith(expect.objectContaining({ run_id: 'run-e' }), '执行', expect.any(Function))
  })

  it('401 时探测企业会话并展示失败', async () => {
    const { round, messages, appliedTexts } = setup()
    h.sendChatStream.mockRejectedValue(Object.assign(new Error('unauthorized'), { status: 401 }))

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(h.probeEnterpriseSession).toHaveBeenCalledTimes(1)
    expect(appliedTexts().at(-1)).toBe('处理失败：unauthorized')
    expect(messages.value[0].workflowAction).toBe('failed')
  })

  it('离线错误交给网络稳定性分类提示', async () => {
    const { round, appliedTexts } = setup()
    h.sendChatStream.mockRejectedValue(new Error('offline'))

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(appliedTexts().at(-1)).not.toContain('处理失败：')
    expect(appliedTexts().at(-1)).toContain('网络')
  })

  it('需要核对的终态不弹任务确认', async () => {
    const { round, deps, messages } = setup()
    feed([{ type: 'done', result: { success: true, response: '执行中', requires_reconciliation: true, task: { type: 'custom', title: '待核对' } } }])

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(messages.value[0].workflowAction).toBe('unknown')
    expect(deps.showTaskConfirm).not.toHaveBeenCalled()
    expect(deps.emitAssistantPush).not.toHaveBeenCalled()
  })

  it('无正文且无完成内容时显示占位文本且不播报', async () => {
    const { round, deps, appliedTexts } = setup()
    feed([{ type: 'done', result: { success: true } }])

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(appliedTexts().at(-1)).toBe('（无内容）')
    expect(deps.queueVoice).not.toHaveBeenCalled()
  })

  it('缓存兜底与正文内的生成占位标记在播报前被清理', async () => {
    const { round, deps } = setup()
    feed([{ type: 'done', result: { success: true, response: '（正在将 Excel 导入数据库）导入完成', data: { cached: true } } }])

    await round.executeRemoteChatRound(['导入'], undefined, scope())

    expect(deps.queueVoice).toHaveBeenCalledWith('导入完成')
    expect(deps.applyPlainTextToMessageIndex.mock.calls.at(-1)?.[2]).toMatchObject({ sameAsPrevious: true })
  })

  it('成功终态不再播报语音时仍落正文', async () => {
    const { round, deps } = setup({ tts: false })
    feed([{ type: 'done', result: { success: true, response: '静默回复' } }])

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(deps.addMessage).not.toHaveBeenCalled()
    expect(deps.applyPlainTextToMessageIndex).toHaveBeenLastCalledWith(0, '静默回复')
    expect(deps.queueVoice).not.toHaveBeenCalled()
  })
})

describe('executeRemoteChatRound 断线续传与超时', () => {
  it.each(['queued', 'running', 'waiting_user', 'waiting_input', 'waiting_auth', 'paused', 'unknown', 'future_state'])('JSON 与 SSE 保留 %s 原运行状态，不触发成功动作', async execution_state => {
    const payload = { success: false, execution_state, run_id: 'original-run',
      response: '原任务进度', task: { type: 'custom' }, autoAction: { type: 'should-not-run' } }
    for (const streamEnabled of [true, false]) {
      h.state.streamEnabled = streamEnabled
      const { round, deps, messages } = setup()
      feed([{ type: 'done', result: payload }])
      deps.chatRequest.requestChatByModeWithTimeout.mockResolvedValue(payload)
      await round.executeRemoteChatRound(['执行'], undefined, scope())
      expect(messages.value[0]).toMatchObject({ content: '原任务进度', workflowAction: execution_state })
      expect(deps.showTaskConfirm).not.toHaveBeenCalled()
      expect(deps.handleAutoAction).not.toHaveBeenCalled()
      expect(deps.syncAgentRunFromPayload).toHaveBeenCalledWith(expect.objectContaining({ run_id: 'original-run' }), '执行', expect.any(Function))
    }
  })

  it('批量业务未完成时逐条保留原回执而非覆盖为批量失败', async () => {
    h.state.streamEnabled = false
    const { round, deps, messages } = setup()
    deps.chatRequest.requestChatByModeBatchWithTimeout.mockResolvedValue({
      batch: true, success: false, results: [
        { success: true, response: '首项完成', execution_state: 'completed' },
        { success: false, response: '第二项等待确认', execution_state: 'waiting_user', run_id: 'waiting-run' },
      ],
    })
    await round.executeRemoteChatRound(['第一项', '第二项'], undefined, scope())
    expect(messages.value.map(message => message.content)).toEqual(['首项完成', '第二项等待确认'])
    expect(messages.value[1].workflowAction).toBe('waiting_user')
    expect(deps.handleAutoAction).not.toHaveBeenCalled()
  })

  it.each(['running', 'blocked'])('继续回执绑定原 %s 任务且不触发业务动作', async status => {
    const { round, deps, messages } = setup()
    feed([{ type: 'done', result: {
      success: status === 'running', response: '查看原导入任务',
      active_turn: { turn_id: 'original-turn', run_id: 'original-run', task_id: 'original-task', status },
      autoAction: { type: 'should-not-run' },
    } }])

    await round.executeRemoteChatRound(['继续'], undefined, scope())

    expect(messages.value[0]).toMatchObject({ workflowAction: status, recoveryTaskId: 'original-task' })
    expect(deps.observeActiveTurn).toHaveBeenCalledWith(expect.objectContaining({
      turnId: 'original-turn', runId: 'original-run', taskId: 'original-task', status,
    }))
    expect(deps.handleAutoAction).not.toHaveBeenCalled()
    expect(h.sendChatStream).toHaveBeenCalledTimes(1)
  })

  it('回放不可用时采用同轮的任务运行状态，替换旧观察超时回执', async () => {
    const { round, deps, messages } = setup()
    h.resumeChatStream.mockResolvedValueOnce({ ok: false, status: 404, headers: new Headers() })
    feed([{ type: 'error', code: 'STREAM_INTERRUPTED', message: '流已中断' }])
    h.getConversation.mockResolvedValueOnce({
      active_turn: { turn_id: 'turn-1', run_id: 'run-1', status: 'running', message: '当前预演 8/21' },
      messages: [{ role: 'assistant', content: '旧提示', metadata: { summary: { turn_id: 'turn-1', status: 'unknown', success: false } } }],
    })

    await round.executeRemoteChatRound(['导入'], undefined, scope())

    expect(messages.value[0]).toMatchObject({ content: '当前预演 8/21', workflowAction: 'running' })
    expect(deps.observeActiveTurn).toHaveBeenCalledWith(expect.objectContaining({ turnId: 'turn-1', runId: 'run-1' }))
    expect(h.sendChatStream).toHaveBeenCalledTimes(1)
  })

  it('超时后只读续传原 turn 并收敛为完成', async () => {
    const { round, deps, messages } = setup()
    deps.chatRequest.resolveChatTimeoutMs.mockReturnValue(120_000)
    let attempt = 0
    h.state.sseScript = async emit => {
      attempt += 1
      if (attempt === 1) {
        emit({ type: 'tool_progress', text: '执行中', run_id: 'run-t' })
        throw Object.assign(new Error('aborted'), { name: 'AbortError' })
      }
      emit({ type: 'token', text: '续传完成' })
      emit({ type: 'done', result: { success: true, response: '续传完成' } })
    }

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(attempt).toBe(2)
    expect(h.sendChatStream).toHaveBeenCalledTimes(1)
    expect(h.resumeChatStream).toHaveBeenCalledWith('turn-1', expect.any(AbortSignal))
    expect(deps.applyPlainTextToMessageIndex).toHaveBeenLastCalledWith(0, '续传完成')
    expect(messages.value[0].workflowAction).toBe('completed')
    expect(messages.value[0].waitingHint).toBeUndefined()
    expect(deps.flushMessagesCache).toHaveBeenCalled()
  })

  it('binds both visible messages to the atomic server receipt so recall uses the server id', async () => {
    const { round, messages } = setup()
    messages.value.push({ role: 'user', content: 'query', time: '', turnId: 'turn-1' })
    h.state.sseScript = async emit => emit({ type: 'done', result: {
      success: true, response: 'answer', history_persistence: { status: 'saved', turn_id: 'turn-1', message_ids: [101, 102], revision: 0 },
    } })
    await round.executeRemoteChatRound(['query'], undefined, scope())
    expect(messages.value.map(message => message.persistence)).toEqual([
      { id: 'server:101', status: 'saved' }, { id: 'server:102', status: 'saved' },
    ])
  })

  it.each(['failed', 'waiting_approval', 'waiting_user'])('重连完整应用 %s 回执和审批/业务状态', async status => {
    const { round, deps, messages } = setup()
    let attempt = 0
    const payload = { success: status !== 'failed', response: '真实终态', execution_state: status,
      data: { status, data: { approval_card: { id: 'approval-1' }, state_updates: [{ type: 'state.update', node_id: 'read', status: 'failed' }] } } }
    h.state.sseScript = async emit => {
      if (++attempt === 1) {
        emit({ type: 'tool_progress', text: '执行中', run_id: 'run-resume' })
        throw new TypeError('network error')
      }
      emit({ type: 'done', result: payload })
    }
    await round.executeRemoteChatRound(['执行'], undefined, scope())
    expect(attempt).toBe(2)
    expect(messages.value[0].workflowAction).toBe(status)
    expect(messages.value[0].content).toBe('真实终态')
    expect(deps.attachApprovalCardToLastAiMessage).toHaveBeenCalledWith(payload)
    expect(deps.attachBusinessResultToLastAiMessage).toHaveBeenCalledWith(payload)
    expect(deps.syncTaskFromChatResponse).toHaveBeenCalledWith(payload, '执行')
    expect(deps.stateSteps.value).toEqual([{ node_id: 'read', status: 'failed', output_summary: '' }])
  })

  it('用户显式停止观察后不会重连，原任务结果仍待回读', async () => {
    const { round, deps, appliedTexts, messages } = setup()
    deps.chatRequest.resolveChatTimeoutMs.mockReturnValue(120_000)
    const aborter = new AbortController()
    let attempt = 0
    h.state.sseScript = async (emit, signal) => {
      attempt += 1
      if (attempt === 1) {
        emit({ type: 'tool_progress', text: '执行中', run_id: 'run-t' })
        await new Promise<void>((resolve) => signal?.addEventListener('abort', () => resolve()))
        throw Object.assign(new Error('aborted'), { name: 'AbortError' })
      }
      throw new Error('network is down')
    }

    const running = round.executeRemoteChatRound(['执行'], undefined, scope({ signal: aborter.signal }))
    await vi.waitFor(() => expect(h.sendChatStream).toHaveBeenCalledTimes(1))
    aborter.abort()
    await running

    expect(attempt).toBe(1)
    expect(h.resumeChatStream).not.toHaveBeenCalled()
    expect(appliedTexts().at(-1)).toContain('对话连接已超时，任务可能仍在执行')
    expect(messages.value[0].workflowAction).toBe('unknown')
  })

  it('无 run_id 的超时标记结果未知但不重放', async () => {
    const { round, deps, appliedTexts } = setup()
    deps.chatRequest.resolveChatTimeoutMs.mockReturnValue(120_000)
    const aborter = new AbortController()
    h.state.sseScript = async (_emit, signal) => {
      await new Promise<void>((resolve) => signal?.addEventListener('abort', () => resolve()))
      throw Object.assign(new Error('aborted'), { name: 'AbortError' })
    }

    const running = round.executeRemoteChatRound(['执行'], undefined, scope({ signal: aborter.signal }))
    await vi.waitFor(() => expect(h.sendChatStream).toHaveBeenCalledTimes(1))
    aborter.abort()
    await running

    expect(appliedTexts().at(-1)).toContain('请求超时（>120s）或已中断')
    expect(h.sendChatStream).toHaveBeenCalledTimes(1)
  })
})

describe('executeRemoteChatRound 非流式回退', () => {
  beforeEach(() => {
    h.state.streamEnabled = false
  })

  it('空消息列表直接返回', async () => {
    const { round, deps } = setup()
    await round.executeRemoteChatRound([], undefined, scope())
    expect(deps.chatRequest.requestChatByModeWithTimeout).not.toHaveBeenCalled()
    expect(deps.addMessage).not.toHaveBeenCalled()
  })

  it('初始归属失效时不发起请求', async () => {
    const { round, deps } = setup()
    h.state.authOk = false
    await round.executeRemoteChatRound(['你好'], undefined, scope())
    expect(deps.chatRequest.requestChatByModeWithTimeout).not.toHaveBeenCalled()
    expect(deps.addMessage).not.toHaveBeenCalled()
  })

  it('身份与当前 MOD 不一致时不发起请求', async () => {
    const { round, deps } = setup()
    h.state.activeModId = 'mod-current'
    await round.executeRemoteChatRound(['你好'], undefined, scope({ identity: 'identity:mod-stale' }))
    expect(deps.chatRequest.requestChatByModeWithTimeout).not.toHaveBeenCalled()
  })

  it('未传 scope 时用会话代次开启本轮并驱动 loading 状态', async () => {
    const { round, deps, sessionId } = setup()
    let resolveRequest: (value: unknown) => void = () => undefined
    deps.chatRequest.requestChatByModeWithTimeout.mockReturnValue(new Promise((resolve) => { resolveRequest = resolve }))

    const running = round.executeRemoteChatRound(['你好'])
    await Promise.resolve()
    expect(deps.chatRequest.requestChatByModeWithTimeout).toHaveBeenCalledWith('你好', 30_000, undefined, expect.objectContaining({ sessionId: 'session-1', isCurrent: expect.any(Function) }))
    expect(deps.chatRequest.setLoadingProgress).toHaveBeenCalledWith('正在整理上下文...', 'session-1')

    resolveRequest({ success: true, response: '你好呀' })
    await running
    expect(deps.addMessage).toHaveBeenCalledWith('你好呀', 'ai', expect.any(Object), expect.any(Object))
    expect(deps.chatRequest.stopLoadingProgress).toHaveBeenCalledWith('session-1')
    expect(sessionId.value).toBe('session-1')
  })

  it('单条成功时挂载全部回执', async () => {
    const { round, deps, stateSteps } = setup()
    const route = routePayload()
    deps.chatRequest.requestChatByModeWithTimeout.mockResolvedValue({
      success: true,
      response: '已完成',
      task: { type: 'custom', title: '任务A', description: '描述A' },
      autoAction: { type: 'show_products_float', query: '5003A' },
      cached: true,
      execution: { committed: true, effect: 'committed', outcome: 'succeeded', idempotency_key: 'k1', intent: 'query' },
      businessResult: { status: 'completed', summary: '查询完成', facts: { count: 2 }, evidence: { completed_tool_count: 1 } },
      route_metadata: route,
      run_id: 'run-json',
      data: { action: 'workflow_done', data: { state_updates: [{ type: 'state.update', node_id: 'n1', status: 'succeeded', output_summary: '完成' }] } },
    })

    await round.executeRemoteChatRound(['查询'], undefined, scope())

    expect(deps.chatRequest.setLoadingProgress).toHaveBeenCalledWith('执行完成，正在整理结果...', 'session-1')
    const extras = deps.addMessage.mock.calls[0][2]
    expect(extras).toMatchObject({
      turnId: 'turn-1',
      routeMetadata: route,
      sameAsPrevious: true,
      execution: expect.objectContaining({ committed: true }),
      businessResult: expect.objectContaining({ summary: '查询完成' }),
    })
    expect(stateSteps.value).toHaveLength(1)
    expect(deps.syncTaskFromChatResponse).toHaveBeenCalledWith(expect.objectContaining({ response: '已完成' }), '查询')
    expect(deps.syncAgentRunFromPayload).toHaveBeenCalledWith(expect.objectContaining({ run_id: 'run-json' }), '查询', expect.any(Function))
    expect(deps.showTaskConfirm).toHaveBeenCalledWith(expect.objectContaining({ title: '任务A' }))
    expect(deps.handleAutoAction).toHaveBeenCalledWith({ type: 'show_products_float', query: '5003A' }, '查询')
    await vi.waitFor(() => expect(deps.attachAgentRunTraceToLastAiMessage).toHaveBeenCalledWith('run-json'))
  })

  it.each(['single', 'batch'])('旧授权回执在 %s 响应中不能触发任务或自动动作', async mode => {
    const { round, deps, messages } = setup()
    const pending = {
      success: true, response: '等待原任务授权', requires_token: true, run_id: 'original-run',
      task: { type: 'custom', title: '未执行任务' }, autoAction: { type: 'show_orders' },
    }
    if (mode === 'batch') {
      deps.chatRequest.requestChatByModeBatchWithTimeout.mockResolvedValue({ success: true, batch: true, results: [pending] })
    } else {
      deps.chatRequest.requestChatByModeWithTimeout.mockResolvedValue(pending)
    }
    await round.executeRemoteChatRound(mode === 'batch' ? ['第一条', '第二条'] : ['执行'], undefined, scope())
    expect(messages.value.at(-1)?.workflowAction).toBe('waiting_auth')
    expect(deps.chatSessionActivity.statuses.value['session-1']).toBe('waiting')
    expect(deps.showTaskConfirm).not.toHaveBeenCalled()
    expect(deps.handleAutoAction).not.toHaveBeenCalled()
    expect(deps.syncAgentRunFromPayload).toHaveBeenCalledWith(expect.objectContaining({ run_id: 'original-run' }), expect.any(String), expect.any(Function))
  })

  it('待授权回执仍优先保留结果未知状态', async () => {
    const { round, deps, messages } = setup()
    deps.chatRequest.requestChatByModeWithTimeout.mockResolvedValue({
      success: true, response: '请核对原任务', requires_token: true, requires_reconciliation: true,
      autoAction: { type: 'show_orders' },
    })
    await round.executeRemoteChatRound(['执行'], undefined, scope())
    expect(messages.value.at(-1)?.workflowAction).toBe('unknown')
    expect(deps.chatSessionActivity.statuses.value['session-1']).toBe('review')
    expect(deps.handleAutoAction).not.toHaveBeenCalled()
  })

  it('单条失败且需要核对时挂载业务结果并同步执行链', async () => {
    const { round, deps, messages } = setup()
    deps.chatRequest.requestChatByModeWithTimeout.mockResolvedValue({
      success: false,
      message: '写入失败',
      requires_reconciliation: true,
      run_id: 'run-fail',
      businessResult: { status: 'unknown', summary: '结果未知', facts: { order_id: 3 } },
    })

    await round.executeRemoteChatRound(['写入'], undefined, scope())

    expect(deps.addMessage).toHaveBeenCalledWith(
      '写入失败',
      'ai',
      expect.objectContaining({ workflowAction: 'unknown', businessResult: expect.objectContaining({ summary: '结果未知' }) }),
      expect.any(Object),
    )
    expect(deps.attachBusinessResultToLastAiMessage).toHaveBeenCalledWith(expect.objectContaining({ success: false }))
    expect(deps.syncAgentRunFromPayload).toHaveBeenCalledWith(expect.objectContaining({ run_id: 'run-fail' }), '写入', expect.any(Function))
    expect(deps.showTaskConfirm).not.toHaveBeenCalled()
    expect(messages.value[0].workflowAction).toBe('unknown')
  })

  it('批量结果逐条写回并只对最后一条动作生效', async () => {
    const { round, deps, currentTask } = setup()
    deps.chatRequest.requestChatByModeBatchWithTimeout.mockResolvedValue({
      success: true,
      batch: true,
      results: [
        { success: true, response: '第一条' },
        { success: false, message: '第二条失败' },
        {
          success: true,
          response: '第三条',
          task: { type: 'custom', title: '批量任务', description: '请处理' },
          autoAction: { type: 'show_orders' },
          run_id: 'run-batch',
          data: { data: { state_updates: [{ type: 'state.update', node_id: 'n9', status: 'succeeded', output_summary: 'ok' }] } },
        },
      ],
    })

    await round.executeRemoteChatRound(['第一条', '第二条', '第三条'], undefined, scope())

    expect(deps.chatRequest.requestChatByModeBatchWithTimeout).toHaveBeenCalledWith(['第一条', '第二条', '第三条'], 90_000, expect.any(Object))
    expect(deps.addMessage).toHaveBeenCalledWith('第一条', 'ai', expect.objectContaining({ turnId: 'turn-1' }), expect.any(Object))
    expect(deps.addMessage).toHaveBeenCalledWith('处理失败: 第二条失败', 'ai', expect.objectContaining({ workflowAction: 'failed' }), expect.any(Object))
    expect(deps.addMessage).toHaveBeenCalledWith('第三条', 'ai', expect.objectContaining({ turnId: 'turn-1' }), expect.any(Object))
    expect(deps.attachBusinessResultToLastAiMessage).toHaveBeenCalledTimes(3)
    expect(deps.attachContextSummaryToLastAiMessage).toHaveBeenCalledTimes(1)
    expect(deps.showTaskConfirm).toHaveBeenCalledWith(expect.objectContaining({ title: '批量任务' }))
    expect(deps.emitAssistantPush).toHaveBeenCalledWith({ title: '批量任务', description: '请处理' })
    expect(deps.handleAutoAction).toHaveBeenCalledWith({ type: 'show_orders' }, '第三条')
    expect(deps.maybeCloseAssistantFloatForShipmentTask).toHaveBeenCalledWith(expect.objectContaining({ title: '批量任务' }), { type: 'show_orders' })
    // 最后一条带任务时不清理已有任务
    expect(currentTask.value).toEqual({ type: 'existing' })
  })

  it('批量中有需要核对的结果时提前返回', async () => {
    const { round, deps } = setup()
    deps.chatRequest.requestChatByModeBatchWithTimeout.mockResolvedValue({
      success: true,
      batch: true,
      results: [
        { success: true, response: '部分完成' },
        { success: false, message: '未知结果', requires_reconciliation: true, run_id: 'run-unknown' },
      ],
    })

    await round.executeRemoteChatRound(['a', 'b'], undefined, scope())

    expect(deps.syncAgentRunFromPayload).toHaveBeenCalledWith(expect.objectContaining({ run_id: 'run-unknown' }), 'a', expect.any(Function))
    expect(deps.showTaskConfirm).not.toHaveBeenCalled()
    expect(deps.handleAutoAction).not.toHaveBeenCalled()
  })

  it('批量整体失败时写一条失败回执', async () => {
    const { round, deps } = setup()
    deps.chatRequest.requestChatByModeBatchWithTimeout.mockResolvedValue({ success: false, batch: true, results: [], message: '网关拒绝' })

    await round.executeRemoteChatRound(['a', 'b'], undefined, scope())

    expect(deps.addMessage).toHaveBeenCalledWith('处理失败: 网关拒绝', 'ai', expect.objectContaining({ workflowAction: 'failed' }), expect.any(Object))
    expect(deps.attachBusinessResultToLastAiMessage).toHaveBeenCalledWith(expect.objectContaining({ success: false }))
  })

  it('请求异常保留 route_metadata 和 unknown，不重派任务', async () => {
    const { round, deps } = setup()
    const route = routePayload()
    deps.chatRequest.requestChatByModeWithTimeout.mockRejectedValue(Object.assign(new Error('上游超时'), { data: { route_metadata: route } }))

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(deps.addMessage).toHaveBeenCalledWith(
      expect.stringContaining('结果未知'),
      'ai',
      expect.objectContaining({ workflowAction: 'unknown', routeMetadata: route }),
      expect.any(Object),
    )
    expect(h.getConversation).toHaveBeenCalledExactlyOnceWith('session-1', { turn_id: 'turn-1' })
    expect(deps.chatRequest.requestChatByModeWithTimeout).toHaveBeenCalledTimes(1)
  })

  it('请求抛出字符串时用兜底文案', async () => {
    const { round, deps } = setup()
    deps.chatRequest.requestChatByModeWithTimeout.mockRejectedValue('网络断开')

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(deps.addMessage).toHaveBeenCalledWith(expect.stringContaining('结果未知'), 'ai', expect.objectContaining({ workflowAction: 'unknown' }), expect.any(Object))
  })

  it.each([false, true])('JSON 断线读取原 turn 完成回执，批量=%s', async batch => {
    const { round, deps, messages } = setup()
    const request = batch ? deps.chatRequest.requestChatByModeBatchWithTimeout : deps.chatRequest.requestChatByModeWithTimeout
    request.mockRejectedValue(new Error('network error'))
    h.getConversation.mockResolvedValue({ turn_receipt: {
      turn_id: 'turn-1', run_id: 'original-run', status: 'completed', message: '原任务持久完成回执',
    } })
    await round.executeRemoteChatRound(batch ? ['a', 'b'] : ['a'], undefined, scope())
    expect(request).toHaveBeenCalledTimes(1)
    expect(h.getConversation).toHaveBeenCalledExactlyOnceWith('session-1', { turn_id: 'turn-1' })
    expect(messages.value[0]).toMatchObject({ content: '原任务持久完成回执', workflowAction: 'completed' })
    expect(deps.handleAutoAction).not.toHaveBeenCalled()
  })

  it('会话切换后只把结果持久化到原会话，不写当前界面', async () => {
    const { round, deps, sessionId } = setup()
    deps.chatRequest.requestChatByModeWithTimeout.mockImplementation(async () => {
      sessionId.value = 'session-2'
      return { success: true, response: '旧会话结果' }
    })

    await round.executeRemoteChatRound(['你好'], undefined, scope())

    expect(h.persistDetachedPlannerResult).toHaveBeenCalledWith({ success: true, response: '旧会话结果' }, 'session-1', expect.any(Function))
    expect(deps.addMessage).not.toHaveBeenCalled()
  })

  it('响应返回后归属失效时不写消息也不持久化', async () => {
    const { round, deps } = setup()
    deps.chatRequest.requestChatByModeWithTimeout.mockImplementation(async () => {
      h.state.authOk = false
      return { success: true, response: '不该出现' }
    })

    await round.executeRemoteChatRound(['你好'], undefined, scope())

    expect(h.persistDetachedPlannerResult).not.toHaveBeenCalled()
    expect(deps.addMessage).not.toHaveBeenCalled()
  })
})

describe('executeRemoteChatRound 状态保护与边界分支', () => {
  it('产品快路径写回执后归属失效即停止后续副作用', async () => {
    const { round, deps, messages } = setup()
    h.state.productKeyword = '5003A'
    h.searchProducts.mockResolvedValue({ success: true, data: [{ id: 1, model_number: '5003A', name: '清漆' }] })
    deps.saveMessage.mockImplementation(async (role: string) => {
      if (role === 'ai') h.state.authOk = false
    })

    await round.executeRemoteChatRound(['查 5003A'], undefined, scope())

    expect(messages.value[0].content).toContain('已帮你打开产品副窗')
    expect(deps.handleAutoAction).not.toHaveBeenCalled()
    expect(deps.syncTaskFromChatResponse).not.toHaveBeenCalled()
  })

  it('产品查询异常后归属失效时不进入统一链路', async () => {
    const { round, deps } = setup()
    h.state.productKeyword = '5003A'
    h.searchProducts.mockImplementation(async () => {
      h.state.authOk = false
      throw new Error('boom')
    })

    await round.executeRemoteChatRound(['查 5003A'], undefined, scope())

    expect(deps.chatRequest.requestChatByModeWithTimeout).not.toHaveBeenCalled()
    expect(h.sendChatStream).not.toHaveBeenCalled()
  })

  it('外部终止信号已触发时立即中止流', async () => {
    const { round, deps } = setup()
    const aborter = new AbortController()
    aborter.abort()
    feed([
      { type: 'token', text: '已收到' },
      { type: 'done', result: { success: true, response: '已收到' } },
    ])

    await round.executeRemoteChatRound(['你好'], undefined, scope({ signal: aborter.signal }))

    expect((h.sendChatStream.mock.calls[0][1] as { signal: AbortSignal }).signal.aborted).toBe(true)
    expect(deps.applyPlainTextToMessageIndex).toHaveBeenLastCalledWith(0, '已收到')
  })

  it('流式卡住超过阈值时标记超时并终断', async () => {
    const { round, appliedTexts } = setup()
    const timers = captureTimers()
    h.state.sseScript = async (_emit, signal) => {
      await new Promise<void>((resolve) => signal?.addEventListener('abort', () => resolve()))
      throw Object.assign(new Error('aborted'), { name: 'AbortError' })
    }

    const running = round.executeRemoteChatRound(['帮我查一下客户'], undefined, scope())
    await vi.waitFor(() => expect(h.sendChatStream).toHaveBeenCalledTimes(1))
    const stall = timers.scheduled.find((timer) => timer.ms === 40_000)
    expect(timers.scheduled.map((timer) => timer.ms)).toContain(40_000)
    expect(stall).toBeDefined()
    stall?.cb()
    await running
    timers.restore()

    expect(appliedTexts().at(-1)).toContain('请求超时（>40s）')
  })

  it('办公表格导入消息不启用流式停滞计时', async () => {
    const { round, deps } = setup()
    const timers = captureTimers()
    feed([{ type: 'done', result: { success: true, response: '导入完成' } }])

    await round.executeRemoteChatRound(['导入 客户.xlsx'], undefined, scope())
    timers.restore()

    expect(timers.scheduled.some((timer) => timer.ms === 40_000)).toBe(false)
    expect(deps.applyPlainTextToMessageIndex).toHaveBeenLastCalledWith(0, '导入完成')
  })

  it('硬超时计时器触发时中断流', async () => {
    const { round, deps, appliedTexts } = setup()
    deps.chatRequest.resolveChatTimeoutMs.mockReturnValue(120_000)
    const timers = captureTimers()
    h.state.sseScript = async (_emit, signal) => {
      await new Promise<void>((resolve) => signal?.addEventListener('abort', () => resolve()))
      throw Object.assign(new Error('aborted'), { name: 'AbortError' })
    }

    const running = round.executeRemoteChatRound(['执行'], undefined, scope())
    await vi.waitFor(() => expect(h.sendChatStream).toHaveBeenCalledTimes(1))
    const kill = timers.scheduled.find((timer) => timer.ms === 120_000)
    expect(kill).toBeDefined()
    kill?.cb()
    await running
    timers.restore()

    expect(appliedTexts().at(-1)).toContain('请求超时（>120s）或已中断')
  })

  it('流式文本按帧合并刷新', async () => {
    const { round, deps, appliedTexts } = setup()
    h.state.sseScript = async (emit) => {
      emit({ type: 'token', text: '第一段' })
      await new Promise((resolve) => setTimeout(resolve, 40))
      emit({ type: 'token', text: '第二段' })
      await new Promise((resolve) => setTimeout(resolve, 40))
      emit({ type: 'done', result: { success: true, response: '第一段第二段' } })
    }

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(appliedTexts()).toContain('第一段')
    expect(deps.applyPlainTextToMessageIndex).toHaveBeenLastCalledWith(0, '第一段第二段')
  })

  it('会话切换后路线、授权与终态事件不再写界面', async () => {
    const { round, deps, sessionId, messages } = setup()
    h.state.sseScript = async (emit) => {
      sessionId.value = 'session-2'
      emit({ type: 'route_metadata', route_metadata: routePayload() })
      emit({ type: 'token', text: '半截' })
      emit({ type: 'requires_token', token_name: 'DB_WRITE_TOKEN', token_description: '写入' })
      emit({ type: 'done', result: { success: true, response: '半截' } })
    }

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(messages.value[0].routeMetadata).toBeUndefined()
    expect(deps.applyPlainTextToMessageIndex).not.toHaveBeenCalled()
    expect(deps.flushMessagesCache).not.toHaveBeenCalled()
  })

  it('streams two conversations independently and applies a background receipt to its original rows', async () => {
    const { sessionId, deps } = setup({ tts: false })
    const aRows = ref<UiChatMessage[]>([{ role: 'user', content: 'Question A', time: '', turnId: 'turn-1' }])
    const bRows = ref<UiChatMessage[]>([{ role: 'user', content: 'Question B', time: '', turnId: 'turn-2' }])
    const persist = vi.fn()
    const release = vi.fn()
    const retainConversationMessages = (id?: string) => {
      const rows = id === 'session-1' ? aRows : bRows
      return {
        messages: rows, persist, release,
        pushStreamingAiShell() {
          rows.value.push({ role: 'ai', content: '', time: '', streamingShell: true })
          return rows.value.length - 1
        },
        applyPlainTextToMessageIndex(index: number, content: string, extras?: Partial<UiChatMessage>) {
          Object.assign(rows.value[index], { content }, extras)
          delete rows.value[index].streamingShell
        },
      }
    }
    const { executeRemoteChatRound } = useChatOrchestrationRemoteRound({
      ...deps, retainConversationMessages,
    } as unknown as Parameters<typeof useChatOrchestrationRemoteRound>[0])
    const streams: Array<{ emit: (event: PlannerSseEvent) => void; finish: () => void }> = []
    h.state.sseScript = emit => new Promise(finish => streams.push({ emit, finish }))
    const a = executeRemoteChatRound(['Question A'], undefined, scope())
    await vi.waitFor(() => expect(streams).toHaveLength(1))
    sessionId.value = 'session-2'
    const b = executeRemoteChatRound(['Question B'], undefined, scope({ sessionId: 'session-2', turnId: 'turn-2' }))
    await vi.waitFor(() => expect(streams).toHaveLength(2))
    expect(deps.chatSessionActivity.statuses.value).toEqual({ 'session-1': 'streaming', 'session-2': 'streaming' })

    streams[0].emit({ type: 'token', text: 'A in progress' })
    await vi.waitFor(() => expect(aRows.value.at(-1)?.content).toBe('A in progress'))
    expect(bRows.value.at(-1)?.content).toBe('')
    streams[0].emit({ type: 'done', result: { success: true, response: 'Answer A', history_persistence: {
      status: 'saved', turn_id: 'turn-1', message_ids: [101, 102],
    } } })
    streams[0].finish()
    await a
    expect(aRows.value.map(row => row.persistence?.id)).toEqual(['server:101', 'server:102'])
    expect(aRows.value.at(-1)?.content).toBe('Answer A')
    expect(bRows.value[0].persistence).toBeUndefined()
    expect(deps.chatSessionActivity.statuses.value).toEqual({ 'session-1': 'ready', 'session-2': 'streaming' })
    expect(deps.syncTaskFromChatResponse).not.toHaveBeenCalled()

    sessionId.value = 'session-1'
    streams[1].emit({ type: 'error', message: 'Model B unavailable' })
    streams[1].finish()
    await b
    expect(bRows.value.at(-1)?.content).toContain('Model B unavailable')
    expect(deps.chatSessionActivity.statuses.value).toEqual({ 'session-1': 'ready', 'session-2': 'error' })
    expect(persist).toHaveBeenCalledTimes(2)
    expect(release).toHaveBeenCalledTimes(2)
  })

  it('附件轨迹累积到当前气泡', async () => {
    const { round, messages } = setup()
    feed([
      { type: 'trace', items: [{ tool: 'read_slice', ok: true, ms: 12 }] },
      { type: 'trace', items: [{ tool: 'parse_csv', ok: false, ms: 3 }] },
      { type: 'done', result: { success: true, response: '完成' } },
    ])

    await round.executeRemoteChatRound(['分析'], undefined, scope())

    expect(messages.value[0].trace).toEqual([
      { tool: 'read_slice', ok: true, ms: 12 },
      { tool: 'parse_csv', ok: false, ms: 3 },
    ])
  })

  it('本轮之后已有新的 AI 消息时不覆盖执行轨迹', async () => {
    const { round, deps, messages } = setup()
    deps.syncTaskFromChatResponse.mockImplementation(() => {
      messages.value.push({ role: 'ai', content: 'later', time: '' })
    })
    feed([{ type: 'done', result: { success: true, response: '完成', run_id: 'run-x' } }])

    await round.executeRemoteChatRound(['执行'], undefined, scope())
    await vi.waitFor(() => expect(deps.syncAgentRunFromPayload).toHaveBeenCalled())
    await Promise.resolve()

    expect(deps.attachAgentRunTraceToLastAiMessage).not.toHaveBeenCalled()
  })

  it('执行链同步失败时被吞掉且不挂轨迹', async () => {
    const { round, deps } = setup()
    deps.syncAgentRunFromPayload.mockRejectedValue(new Error('sync failed'))
    feed([{ type: 'done', result: { success: true, response: '完成', run_id: 'run-y' } }])

    await round.executeRemoteChatRound(['执行'], undefined, scope())
    await vi.waitFor(() => expect(deps.syncAgentRunFromPayload).toHaveBeenCalled())
    await Promise.resolve()

    expect(deps.attachAgentRunTraceToLastAiMessage).not.toHaveBeenCalled()
  })

  it('续传只补齐终态，不重复授权等副作用', async () => {
    const { round, messages } = setup()
    let attempt = 0
    h.state.sseScript = async emit => {
      attempt += 1
      if (attempt === 1) {
        emit({ type: 'tool_progress', text: '执行中', run_id: 'run-r' })
        throw Object.assign(new Error('aborted'), { name: 'AbortError' })
      }
      emit({ type: 'error', message: '回放提示', requires_reconciliation: true })
      emit({ type: 'requires_token', token_name: 'DB_WRITE_TOKEN' })
      emit({ type: 'token', text: '续传正文' })
      emit({ type: 'done', result: { success: true, response: '续传正文' } })
    }

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(attempt).toBe(2)
    expect(messages.value[0].workflowAction).toBe('unknown')
    expect(messages.value[0].content).toContain('结果未知')
  })

  it('回读历史期间会话切换则放弃回执', async () => {
    const { round, sessionId, appliedTexts } = setup()
    feed([{ type: 'token', text: '半截' }])
    h.getConversation.mockImplementation(async () => {
      sessionId.value = 'session-2'
      throw new Error('switch')
    })

    await round.executeRemoteChatRound(['继续'], undefined, scope())

    expect(appliedTexts()).toEqual([])
  })

  it('延迟回读未拿到完成态时保留失败回执', async () => {
    vi.useFakeTimers()
    const { round, appliedTexts } = setup()
    feed([{ type: 'token', text: '半截' }])
    h.getConversation
      .mockRejectedValueOnce(new Error('nohistory'))
      .mockResolvedValueOnce({
        success: true,
        messages: [{ role: 'assistant', content: '仍在生成', metadata: { summary: { turn_id: 'turn-1', status: 'running' } } }],
      })

    await round.executeRemoteChatRound(['继续'], undefined, scope())
    const before = appliedTexts().length
    await vi.advanceTimersByTimeAsync(1500)

    expect(appliedTexts()).toHaveLength(before)
  })

  it('延迟回读时界面消息已清空则跳过覆盖', async () => {
    vi.useFakeTimers()
    const { round, messages, appliedTexts } = setup()
    feed([{ type: 'token', text: '半截' }])
    h.getConversation
      .mockRejectedValueOnce(new Error('nohistory'))
      .mockImplementationOnce(async () => {
        messages.value = []
        return {
          success: true,
          messages: [{ role: 'assistant', content: '完整回复', metadata: { summary: { turn_id: 'turn-1', status: 'completed', success: true } } }],
        }
      })

    await round.executeRemoteChatRound(['继续'], undefined, scope())
    const before = appliedTexts().length
    await vi.advanceTimersByTimeAsync(1500)

    expect(appliedTexts()).toHaveLength(before)
  })

  it.each([
    ['workflow_confirmation_required', '已生成计划，等待你确认执行...'],
    ['workflow_failed', '执行失败，正在整理错误信息...'],
  ])('解析阶段 %s 时给出对应进度提示', async (action, label) => {
    h.state.streamEnabled = false
    const { round, deps } = setup()
    deps.chatRequest.requestChatByModeWithTimeout.mockResolvedValue({ success: true, response: '完成', data: { action } })

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(deps.chatRequest.setLoadingProgress).toHaveBeenCalledWith(label, 'session-1')
  })

  it('解析阶段归属失效时放弃写回执', async () => {
    h.state.streamEnabled = false
    const { round, deps } = setup()
    deps.chatRequest.requestChatByModeWithTimeout.mockResolvedValue({ success: true, response: '不该出现' })
    deps.chatRequest.setLoadingProgress.mockImplementation((label: string) => {
      if (label === '已收到响应，正在解析执行计划...') h.state.authOk = false
    })

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(deps.addMessage).not.toHaveBeenCalled()
  })

  it('批量写回执后归属失效即停止后续条目', async () => {
    h.state.streamEnabled = false
    const { round, deps, messages } = setup()
    deps.addMessage.mockImplementation((content: string, role: 'user' | 'ai' | 'task' = 'ai') => {
      messages.value.push({ role, content, time: '' })
      if (role === 'ai') h.state.authOk = false
    })
    deps.chatRequest.requestChatByModeBatchWithTimeout.mockResolvedValue({
      success: true,
      batch: true,
      results: [{ success: true, response: '一' }, { success: true, response: '二' }],
    })

    await round.executeRemoteChatRound(['a', 'b'], undefined, scope())

    expect(deps.addMessage).toHaveBeenCalledTimes(1)
    expect(deps.showTaskConfirm).not.toHaveBeenCalled()
  })

  it('批量同步执行链后归属失效即停止后续条目', async () => {
    h.state.streamEnabled = false
    const { round, deps } = setup()
    deps.syncAgentRunFromPayload.mockImplementation(async () => {
      h.state.authOk = false
    })
    deps.chatRequest.requestChatByModeBatchWithTimeout.mockResolvedValue({
      success: true,
      batch: true,
      results: [{ success: true, response: '一' }, { success: true, response: '二' }],
    })

    await round.executeRemoteChatRound(['a', 'b'], undefined, scope())

    expect(deps.addMessage).toHaveBeenCalledTimes(1)
    expect(deps.attachAgentRunTraceToLastAiMessage).not.toHaveBeenCalled()
  })

  it('批量失败条目同步执行链后归属失效时不再挂轨迹', async () => {
    h.state.streamEnabled = false
    const { round, deps } = setup()
    let syncCalls = 0
    deps.syncAgentRunFromPayload.mockImplementation(async () => {
      syncCalls += 1
      if (syncCalls >= 2) h.state.authOk = false
    })
    deps.chatRequest.requestChatByModeBatchWithTimeout.mockResolvedValue({
      success: true,
      batch: true,
      results: [
        { success: true, response: '一' },
        { success: false, message: '失败', requires_reconciliation: true, run_id: 'run-b' },
      ],
    })

    await round.executeRemoteChatRound(['a', 'b'], undefined, scope())

    expect(deps.attachAgentRunTraceToLastAiMessage).not.toHaveBeenCalledWith('run-b')
  })

  it('批量最后一条只带产品浮窗动作时清理当前任务', async () => {
    h.state.streamEnabled = false
    const { round, deps, currentTask } = setup()
    deps.chatRequest.requestChatByModeBatchWithTimeout.mockResolvedValue({
      success: true,
      batch: true,
      results: [{ success: true, response: '在售', autoAction: { type: 'show_products_float', query: '5003A' } }],
    })

    await round.executeRemoteChatRound(['a', 'b'], undefined, scope())

    expect(currentTask.value).toBeNull()
    expect(deps.handleAutoAction).toHaveBeenCalledWith({ type: 'show_products_float', query: '5003A' }, 'b')
  })

  it('单条写回执后归属失效即停止挂载', async () => {
    h.state.streamEnabled = false
    const { round, deps, messages } = setup()
    deps.addMessage.mockImplementation((content: string, role: 'user' | 'ai' | 'task' = 'ai') => {
      messages.value.push({ role, content, time: '' })
      if (role === 'ai') h.state.authOk = false
    })
    deps.chatRequest.requestChatByModeWithTimeout.mockResolvedValue({ success: true, response: '完成' })

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(deps.addMessage).toHaveBeenCalledTimes(1)
    expect(deps.syncTaskFromChatResponse).not.toHaveBeenCalled()
  })

  it('单条同步执行链后归属失效时不再挂轨迹', async () => {
    h.state.streamEnabled = false
    const { round, deps } = setup()
    deps.syncAgentRunFromPayload.mockImplementation(async () => {
      h.state.authOk = false
    })
    deps.chatRequest.requestChatByModeWithTimeout.mockResolvedValue({ success: true, response: '完成', run_id: 'run-s' })

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(deps.syncTaskFromChatResponse).toHaveBeenCalled()
    expect(deps.attachAgentRunTraceToLastAiMessage).not.toHaveBeenCalled()
  })

  it('单条成功但需要核对时不弹任务确认', async () => {
    h.state.streamEnabled = false
    const { round, deps, messages } = setup()
    deps.chatRequest.requestChatByModeWithTimeout.mockResolvedValue({
      success: true,
      response: '执行中',
      requires_reconciliation: true,
      task: { type: 'custom', title: '待核对' },
    })

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(messages.value[0].workflowAction).toBe('unknown')
    expect(deps.showTaskConfirm).not.toHaveBeenCalled()
  })

  it('单条成功只带产品浮窗动作时清理当前任务', async () => {
    h.state.streamEnabled = false
    const { round, deps, currentTask } = setup()
    deps.chatRequest.requestChatByModeWithTimeout.mockResolvedValue({
      success: true,
      response: '在售',
      autoAction: { type: 'show_products_float', query: '5003A' },
    })

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(currentTask.value).toBeNull()
    expect(deps.handleAutoAction).toHaveBeenCalledWith({ type: 'show_products_float', query: '5003A' }, '执行')
  })

  it('单条失败同步执行链后归属失效时不再挂轨迹', async () => {
    h.state.streamEnabled = false
    const { round, deps } = setup()
    deps.syncAgentRunFromPayload.mockImplementation(async () => {
      h.state.authOk = false
    })
    deps.chatRequest.requestChatByModeWithTimeout.mockResolvedValue({
      success: false,
      message: '写入失败',
      requires_reconciliation: true,
      run_id: 'run-f',
    })

    await round.executeRemoteChatRound(['执行'], undefined, scope())

    expect(deps.addMessage).toHaveBeenCalledTimes(1)
    expect(deps.attachAgentRunTraceToLastAiMessage).not.toHaveBeenCalled()
  })
})

describe('SSE rendering work bounds', () => {
  it('coalesces 160 token updates without rebuilding tool steps or progress per token', async () => {
    const { round, messages, deps } = setup({ tts: false })
    const changes = vi.fn()
    const stop = watch(() => messages.value[0]?.liveSteps, changes, { flush: 'sync' })
    const chunks = Array.from({ length: 160 }, () => ({ type: 'token' as const, text: '字' }))
    feed([
      { type: 'tool_call', phase: 'started', node_id: 'lookup', tool_id: 'crm', action: 'query' },
      ...chunks,
      { type: 'tool_call', phase: 'finished', node_id: 'lookup', tool_id: 'crm', action: 'query', success: true },
      { type: 'done', result: { success: true, response: '字'.repeat(160) } },
    ])
    try {
      await round.executeRemoteChatRound(['查询客户'], undefined, scope())
      expect(messages.value[0].liveSteps).toHaveLength(1)
      expect(messages.value[0].liveSteps?.[0]).toMatchObject({ id: 'lookup', state: 'success' })
      expect(changes.mock.calls.length).toBeGreaterThanOrEqual(1)
      expect(changes.mock.calls.length).toBeLessThanOrEqual(2)
      const textUpdates = deps.chatRequest.setLoadingProgress.mock.calls
        .filter(([text]) => text === '正在生成回复…')
      expect(textUpdates).toHaveLength(1)
      expect(messages.value[0].content).toBe('字'.repeat(160))
    } finally {
      stop()
    }
  })
})
