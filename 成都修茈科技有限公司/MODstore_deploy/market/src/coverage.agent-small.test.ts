import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick, reactive } from 'vue'

const mockApi = vi.hoisted(() => ({
  verifyAdminDigestCode: vi.fn(),
  listButlerSkills: vi.fn(),
  runESkill: vi.fn(),
  agentCorpIntakeFill: vi.fn(),
  butlerAllHandsReportStartSession: vi.fn(),
  workbenchGetSession: vi.fn(),
}))
const mockAuthStore = vi.hoisted(() => ({
  adminUiUnlocked: false,
  setAdminDigestUnlock: vi.fn(),
}))
const mockAgentStore = vi.hoisted(() => ({
  consentGiven: false,
  pendingAction: null as unknown,
  setPendingAction: vi.fn((action: unknown) => {
    mockAgentStore.pendingAction = action
  }),
}))
const mockWalletStore = vi.hoisted(() => ({
  balance: null as number | null,
}))
let mockRoute: { name?: string; fullPath: string }
const mockRegisteredSkills = vi.hoisted(() => [] as any[])
const mockSpeech = vi.hoisted(() => ({
  startListening: vi.fn(),
  stopListening: vi.fn(async () => ''),
  signalEndOfSpeech: vi.fn(),
  abort: vi.fn(),
  interimText: { value: '' },
  loadingHint: { value: '' },
  sessionReady: { value: false },
}))
const mockStreamingTts = vi.hoisted(() => ({
  speak: vi.fn(async () => undefined),
  stop: vi.fn(),
}))
const mockBridgeState = vi.hoisted(() => ({
  bridge: null as any,
  waitForBridge: vi.fn(async () => mockBridgeState.bridge),
  applyDraftSafe: vi.fn(() => true),
  scrollToIntake: vi.fn(),
}))

vi.mock('./api', () => ({ api: mockApi }))
vi.mock('./stores/auth', () => ({ useAuthStore: () => mockAuthStore }))
vi.mock('./stores/agent', () => ({ useAgentStore: () => mockAgentStore }))
vi.mock('./stores/wallet', () => ({ useWalletStore: () => mockWalletStore }))
vi.mock('vue-router', () => ({ useRoute: () => mockRoute }))
vi.mock('./utils/agent/agentSkillRegistry', () => ({
  skillRegistry: {
    register: (skill: any) => mockRegisteredSkills.push(skill),
  },
}))
vi.mock('./composables/useSpeechRecognition', () => ({ useSpeechRecognition: () => mockSpeech }))
vi.mock('./composables/asr/FunASRBackend', () => ({
  FunASRBackend: class {
    isAvailable() { return true }
  },
}))
vi.mock('./composables/asr/WebSpeechBackend', () => ({
  WebSpeechBackend: class {
    isAvailable() { return false }
  },
}))
vi.mock('./composables/useStreamingTts', () => ({
  useStreamingTts: () => mockStreamingTts,
  ttsConfigFromPersonalSettings: (settings: unknown) => ({ settings }),
}))
vi.mock('./utils/personalSettings', () => ({
  loadPersonalSettings: () => ({ voice: 'alloy' }),
}))
vi.mock('./corp-butler/contactIntakeBridge', () => ({
  waitForBridge: (...args: unknown[]) => mockBridgeState.waitForBridge(...args),
  applyDraftSafe: (...args: unknown[]) => mockBridgeState.applyDraftSafe(...args),
  scrollToIntake: () => mockBridgeState.scrollToIntake(),
}))
vi.mock('./corp-butler/corpViewport', () => ({
  intakeFormPlacementHint: () => '页面下方',
}))
vi.mock('./content/siteKnowledge', () => ({
  resolveCorpPageId: (route: string) => (route.includes('contact') ? 'contact' : 'home'),
}))

function makeBridge(overrides: Record<string, unknown> = {}) {
  return {
    isSubmitted: vi.fn(() => false),
    getState: vi.fn(() => ({ name: '', email: '' })),
    goToStep: vi.fn(),
    ...overrides,
  }
}

afterEach(() => {
  mockApi.verifyAdminDigestCode.mockReset()
  mockApi.listButlerSkills.mockReset()
  mockApi.runESkill.mockReset()
  mockApi.agentCorpIntakeFill.mockReset()
  mockApi.butlerAllHandsReportStartSession.mockReset()
  mockApi.workbenchGetSession.mockReset()
  mockAuthStore.adminUiUnlocked = false
  mockAuthStore.setAdminDigestUnlock.mockClear()
  mockAgentStore.consentGiven = false
  mockAgentStore.pendingAction = null
  mockAgentStore.setPendingAction.mockClear()
  mockWalletStore.balance = null
  mockRegisteredSkills.length = 0
  mockSpeech.startListening.mockReset()
  mockSpeech.stopListening.mockReset().mockResolvedValue('')
  mockSpeech.signalEndOfSpeech.mockClear()
  mockSpeech.abort.mockClear()
  mockStreamingTts.speak.mockReset().mockResolvedValue(undefined)
  mockStreamingTts.stop.mockClear()
  mockBridgeState.bridge = null
  mockBridgeState.waitForBridge.mockClear()
  mockBridgeState.applyDraftSafe.mockReset().mockReturnValue(true)
  mockBridgeState.scrollToIntake.mockClear()
  vi.useRealTimers()
  vi.resetModules()
  vi.restoreAllMocks()
})

describe('small composable and agent skill coverage', () => {
  it('normalizes and verifies admin digest unlock flows', async () => {
    const { normalizeAdminDigestCode, useAdminDigestUnlock } = await import('./composables/useAdminDigestUnlock')
    expect(normalizeAdminDigestCode(' ab-12-z9-cd ')).toBe('AB129C')

    mockAuthStore.adminUiUnlocked = true
    const unlocked = useAdminDigestUnlock()
    await expect(unlocked.ensureAdminDigestUnlocked()).resolves.toBe(true)

    mockAuthStore.adminUiUnlocked = false
    const pending = unlocked.ensureAdminDigestUnlocked({ title: 'T', submitLabel: 'Go', hint: 'H' })
    expect(unlocked.open.value).toBe(true)
    expect(unlocked.dialogTitle.value).toBe('T')
    unlocked.close()
    await expect(pending).resolves.toBe(false)

    unlocked.code.value = 'xx'
    await expect(unlocked.submitVerify()).resolves.toBe(false)
    expect(unlocked.err.value).toContain('请输入恰好 6 位')

    const success = unlocked.ensureAdminDigestUnlocked()
    unlocked.code.value = ' a1 b2 c3 '
    mockApi.verifyAdminDigestCode.mockResolvedValueOnce({ ok: true, expires_at: 'tomorrow' })
    await expect(unlocked.submitVerify()).resolves.toBe(true)
    await expect(success).resolves.toBe(true)
    expect(mockAuthStore.setAdminDigestUnlock).toHaveBeenCalledWith('tomorrow')

    unlocked.code.value = 'ABCDEF'
    mockApi.verifyAdminDigestCode.mockResolvedValueOnce({ ok: false })
    await expect(unlocked.submitVerify()).resolves.toBe(false)
    expect(unlocked.err.value).toContain('校验失败')

    mockApi.verifyAdminDigestCode.mockRejectedValueOnce(new Error('身份码无效'))
    await expect(unlocked.submitVerify()).resolves.toBe(false)
    expect(unlocked.err.value).toContain('市场 API 与身份码来源一致')
  })

  it('resolves danger confirm promises and exposes shared state', async () => {
    const { confirmDanger, resolveDangerConfirm, useDangerConfirmState } = await import('./composables/useDangerConfirm')
    const state = useDangerConfirmState()
    const promise = confirmDanger({ title: '删除', message: '确认删除？', destructive: true })
    expect(state.open.value).toBe(true)
    expect(state.options.value?.title).toBe('删除')
    resolveDangerConfirm(true)
    await expect(promise).resolves.toBe(true)
    expect(state.open.value).toBe(false)
    expect(state.options.value).toBeNull()

    const cancelled = confirmDanger({ title: '取消', message: '取消？' })
    resolveDangerConfirm(false)
    await expect(cancelled).resolves.toBe(false)
  })

  it('generates and dismisses proactive agent suggestions', async () => {
    mockRoute = reactive({ name: 'home', fullPath: '/home' })
    const { useAgentSuggestions } = await import('./composables/agent/useAgentSuggestions')
    const suggestions = useAgentSuggestions()
    expect(suggestions.currentSuggestion.value).toBeNull()

    mockAgentStore.consentGiven = true
    mockWalletStore.balance = 5
    mockRoute.fullPath = '/wallet'
    await nextTick()
    expect(suggestions.currentSuggestion.value?.id).toBe('low-balance')
    suggestions.dismiss('low-balance')
    expect(suggestions.currentSuggestion.value).toBeNull()

    mockWalletStore.balance = 100
    mockRoute.name = 'ai-store'
    mockRoute.fullPath = '/ai-store'
    await nextTick()
    expect(suggestions.currentSuggestion.value?.id).toBe('ai-store-hint')
    suggestions.dismiss('ai-store-hint')
    mockRoute.fullPath = '/ai-store?page=2'
    await nextTick()
    expect(suggestions.currentSuggestion.value).toBeNull()
  })

  it('requests privacy permissions through auto and pending confirmation paths', async () => {
    const { usePrivacyManager } = await import('./composables/agent/usePrivacyManager')
    const privacy = usePrivacyManager()
    await expect(privacy.requestAction('read', 'low', '读取')).resolves.toBe(true)

    const pending = privacy.requestAction('delete', 'high', '删除', { id: 1 })
    expect(mockAgentStore.setPendingAction).toHaveBeenCalled()
    const action = mockAgentStore.pendingAction as { id: string; resolve: (ok: boolean) => void; args: Record<string, unknown> }
    expect(action.id).toBe('action-1')
    expect(action.args).toEqual({ id: 1 })
    action.resolve(false)
    await expect(pending).resolves.toBe(false)
    expect(mockAgentStore.pendingAction).toBeNull()
  })

  it('fetches remote ESkills, registers active skills, and adapts execution results', async () => {
    const { useESkillRuntime } = await import('./composables/agent/useESkillRuntime')
    const runtime = useESkillRuntime()
    mockApi.listButlerSkills.mockResolvedValueOnce([
      {
        id: 1,
        skill_id: 's1',
        name: '远程技能',
        description: 'desc',
        version: '1.0',
        trigger_keywords: ['k'],
        trigger_intent: ['i'],
        permission: 'execute',
        created_at: '2026-01-01T00:00:00Z',
        usage_count: 3,
        is_active: true,
      },
      {
        id: 2,
        skill_id: 's2',
        name: '禁用技能',
        description: 'desc',
        version: '1.0',
        trigger_keywords: [],
        trigger_intent: [],
        permission: 'read',
        created_at: '2026-01-01T00:00:00Z',
        usage_count: 0,
        is_active: false,
      },
    ])

    await runtime.fetchAndRegisterRemoteSkills()
    expect(runtime.remoteSkills.value).toHaveLength(2)
    expect(mockRegisteredSkills).toHaveLength(1)
    expect(mockRegisteredSkills[0].id).toBe('remote:s1')

    mockApi.runESkill.mockResolvedValueOnce({ success: true, result: '执行成功' })
    await expect(mockRegisteredSkills[0].execute({ route: '/r', userMessage: 'u', pageSummary: 'p' }, { x: 1 })).resolves.toEqual({
      success: true,
      message: '执行成功',
      assistantReply: '执行成功',
    })

    mockApi.runESkill.mockRejectedValueOnce(new Error('boom'))
    await expect(mockRegisteredSkills[0].execute({ route: '/r', userMessage: 'u', pageSummary: 'p' })).resolves.toEqual({
      success: false,
      message: 'boom',
    })

    mockApi.listButlerSkills.mockRejectedValueOnce(new Error('list failed'))
    await runtime.fetchAndRegisterRemoteSkills()
    expect(runtime.error.value).toBe('list failed')
  })

  it('drives voice input speak/listen/stop/mute flows', async () => {
    const { useVoiceInput } = await import('./composables/agent/useVoiceInput')
    const onFinalText = vi.fn(async () => undefined)
    const voice = useVoiceInput(onFinalText)
    expect(voice.isSupported).toBe(true)

    await voice.speak('你好')
    expect(mockStreamingTts.speak).toHaveBeenCalledWith('你好')
    expect(voice.state.value).toBe('idle')

    voice.toggleMute()
    expect(voice.muted.value).toBe(true)
    expect(mockStreamingTts.stop).toHaveBeenCalled()
    await voice.speak('不会播放')
    expect(mockStreamingTts.speak).toHaveBeenCalledTimes(1)

    voice.toggleMute()
    voice.startListening()
    const [onResult, onError] = mockSpeech.startListening.mock.calls[0]
    onResult({ text: '  完成  ', isFinal: true })
    await Promise.resolve()
    await Promise.resolve()
    expect(onFinalText).toHaveBeenCalledWith('完成')
    expect(mockSpeech.abort).toHaveBeenCalled()

    voice.startListening()
    onError('识别失败')
    expect(voice.error.value).toBe('识别失败')
    expect(voice.state.value).toBe('idle')

    mockSpeech.stopListening.mockResolvedValueOnce('  手动停止  ')
    voice.startListening()
    await voice.stopListening()
    expect(mockSpeech.signalEndOfSpeech).toHaveBeenCalled()
    expect(onFinalText).toHaveBeenCalledWith('手动停止')

    mockSpeech.stopListening.mockResolvedValueOnce('')
    voice.startListening()
    await voice.stopListening()
    expect(voice.error.value).toBe('未识别到文字，请再试一次或使用文字输入。')

    voice.stopAll()
    expect(voice.state.value).toBe('idle')
  })

  it('matches and executes contact intake skill flows', async () => {
    const {
      executeCorpIntakeMatch,
      matchCorpIntakeIntent,
      runIntakeFillFromMessage,
      runIntakeQuickTask,
    } = await import('./composables/agent/skills/corpIntakeSkill')

    expect(matchCorpIntakeIntent({ route: '/contact', userMessage: '帮我填写需求问卷' } as any)).toEqual({ kind: 'fill' })
    expect(matchCorpIntakeIntent({ route: '/contact', userMessage: '跳到联系方式' } as any)).toEqual({ kind: 'step', stepId: 'contact' })
    expect(matchCorpIntakeIntent({ route: '/contact', userMessage: '提交前核对' } as any)).toEqual({ kind: 'review' })
    expect(matchCorpIntakeIntent({ route: '/pricing', userMessage: '帮我填写需求问卷' } as any)).toBeNull()

    await expect(runIntakeFillFromMessage('msg', 'summary')).resolves.toMatchObject({ success: true, assistantReply: expect.stringContaining('问卷尚未就绪') })
    expect(mockBridgeState.scrollToIntake).toHaveBeenCalled()

    mockBridgeState.bridge = makeBridge({ isSubmitted: vi.fn(() => true) })
    await expect(runIntakeFillFromMessage('msg', 'summary')).resolves.toMatchObject({ assistantReply: expect.stringContaining('已提交过') })

    mockBridgeState.bridge = makeBridge()
    mockApi.agentCorpIntakeFill.mockResolvedValueOnce({ success: true, reply: '', draft: {} })
    await expect(runIntakeFillFromMessage('msg', 'summary')).resolves.toMatchObject({ assistantReply: expect.stringContaining('未能从描述中解析') })

    mockApi.agentCorpIntakeFill.mockResolvedValueOnce({ success: true, reply: '已生成', draft: { name: '张三', directions: ['自动化'] } })
    await expect(runIntakeFillFromMessage('msg', 'summary')).resolves.toMatchObject({ assistantReply: expect.stringContaining('已尝试写入') })
    expect(mockBridgeState.applyDraftSafe).toHaveBeenCalledWith({ name: '张三', directions: ['自动化'] })

    mockBridgeState.applyDraftSafe.mockReturnValueOnce(false)
    mockApi.agentCorpIntakeFill.mockResolvedValueOnce({ success: true, draft: { name: '李四' } })
    await expect(runIntakeFillFromMessage('msg', 'summary')).resolves.toMatchObject({ assistantReply: expect.stringContaining('无法继续预填') })

    mockApi.agentCorpIntakeFill.mockRejectedValueOnce(new Error('api down'))
    await expect(runIntakeFillFromMessage('msg', 'summary')).resolves.toMatchObject({ assistantReply: expect.stringContaining('智能预填暂时不可用') })

    const bridge = makeBridge()
    mockBridgeState.bridge = bridge
    await expect(executeCorpIntakeMatch({ kind: 'review' }, { userMessage: '', pageSummary: '' } as any)).resolves.toMatchObject({ assistantReply: expect.stringContaining('核对并提交') })
    expect(bridge.goToStep).toHaveBeenCalledWith('review')
    await expect(executeCorpIntakeMatch({ kind: 'step', stepId: 'plan' }, { userMessage: '', pageSummary: '' } as any)).resolves.toMatchObject({ assistantReply: expect.stringContaining('计划') })
    expect(bridge.goToStep).toHaveBeenCalledWith('plan')

    await expect(runIntakeQuickTask({ label: '去填写', task: 'intake_step', payload: { stepId: 'contact' } } as any)).resolves.toMatchObject({ assistantReply: expect.stringContaining('contact') })
    await expect(runIntakeQuickTask({ label: '核对', task: 'intake_review', payload: {} } as any)).resolves.toMatchObject({ assistantReply: expect.stringContaining('核对页') })
    await expect(runIntakeQuickTask({ label: '空任务' } as any)).resolves.toBeNull()
  })

  it('executes ask-all-hands success, fallback, and error paths', async () => {
    const { askAllHandsSkill } = await import('./composables/agent/skills/skillAllHandsAsk')
    await expect(askAllHandsSkill.execute({ userMessage: '' } as any)).resolves.toMatchObject({
      success: false,
      message: '需要先告诉我要问员工大会什么问题',
    })

    mockApi.butlerAllHandsReportStartSession.mockResolvedValueOnce({ session_id: 's1' })
    mockApi.workbenchGetSession.mockResolvedValueOnce({
      status: 'done',
      artifact: {
        all_hands_report: {
          ok: true,
          summary: { total: 2 },
          synthesized_answer: {
            question: 'q',
            markdown: '综合答案',
            cited_employees: ['E1', 'E2'],
            generated_at: 'now',
            model: 'm',
          },
        },
      },
    })
    await expect(askAllHandsSkill.execute({ userMessage: '/全员大会 今天有什么风险？' } as any)).resolves.toMatchObject({
      success: true,
      assistantReply: expect.stringContaining('综合答案'),
    })

    mockApi.butlerAllHandsReportStartSession.mockResolvedValueOnce({ session_id: 's2' })
    mockApi.workbenchGetSession.mockResolvedValueOnce({
      status: 'done',
      artifact: {
        all_hands_report: {
          ok: true,
          employees: [{ employee_id: 'E1', name: '员工', status: 'done' }],
          synthesized_answer: { question: 'q', markdown: '', cited_employees: [], generated_at: 'now', model: 'm', error: 'LLM down' },
        },
      },
    })
    await expect(askAllHandsSkill.execute({ userMessage: '问全员库存状态', } as any, { question: '库存状态' })).resolves.toMatchObject({
      success: true,
      assistantReply: expect.stringContaining('综合答复异常'),
    })

    mockApi.butlerAllHandsReportStartSession.mockResolvedValueOnce({})
    await expect(askAllHandsSkill.execute({ userMessage: '库存状态' } as any)).resolves.toMatchObject({
      success: false,
      assistantReply: expect.stringContaining('后端未返回 session_id'),
    })

    mockApi.butlerAllHandsReportStartSession.mockResolvedValueOnce({ session_id: 's3' })
    mockApi.workbenchGetSession.mockResolvedValueOnce({ status: 'error', error: 'worker failed' })
    await expect(askAllHandsSkill.execute({ userMessage: '库存状态' } as any)).resolves.toMatchObject({
      success: false,
      message: expect.stringContaining('worker failed'),
    })
  })
})
