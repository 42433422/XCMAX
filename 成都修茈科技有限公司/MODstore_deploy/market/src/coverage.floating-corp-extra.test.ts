import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, shallowMount } from '@vue/test-utils'

const mockRunIntakeTask = vi.hoisted(() => vi.fn(async () => ({ success: true })))
const mockHandleInput = vi.hoisted(() => vi.fn(async () => 'ok'))
const mockRunContactAiAssistFill = vi.hoisted(() => vi.fn())
const mockStreamingTts = vi.hoisted(() => ({
  speak: vi.fn(async () => undefined),
  stop: vi.fn(),
}))
const mockAgentStore = vi.hoisted(() => ({
  isOpen: false,
  showPermissionDialog: false,
  position: { x: 20, y: 20 },
  consentGiven: false,
  isLoading: false,
  openPanel: vi.fn(function (this: any) { this.isOpen = true }),
  grantConsent: vi.fn(function (this: any) { this.consentGiven = true; this.showPermissionDialog = false }),
  dismissLater: vi.fn(function (this: any) { this.showPermissionDialog = false }),
  savePosition: vi.fn(function (this: any, x: number, y: number) { this.position = { x, y } }),
  addMessage: vi.fn(),
  updateLastMessage: vi.fn(),
}))

vi.mock('pinia', async (importOriginal) => {
  const actual = await importOriginal<typeof import('pinia')>()
  const { toRef } = await import('vue')
  return {
    ...actual,
    storeToRefs: (store: Record<string, unknown>) => {
      const out: Record<string, unknown> = {}
      for (const key of Object.keys(store)) {
        if (typeof store[key] !== 'function') out[key] = toRef(store, key)
      }
      return out
    },
  }
})

vi.mock('./stores/agent', () => ({ useAgentStore: () => mockAgentStore }))
vi.mock('./composables/agent/useCorpAgentEngine', () => ({
  useCorpAgentEngine: () => ({ handleInput: mockHandleInput, runIntakeTask: mockRunIntakeTask }),
}))
vi.mock('./corp-butler/corpViewport', () => ({
  isCorpMobileViewport: () => true,
  intakeFormPlacementHint: () => '页面下方',
}))
vi.mock('./corp-butler/corpBallPosition', () => ({
  clampCorpBallPosition: (x: number, y: number) => ({ x, y }),
  saveCorpBallPosition: (x: number, y: number) => ({ x: Math.max(0, x), y: Math.max(0, y) }),
}))
vi.mock('./content/siteKnowledge', () => ({
  isContactPagePath: (path: string) => path.includes('contact'),
}))
vi.mock('./corp-butler/contactIntakeBridge', () => ({
  runContactAiAssistFill: (...args: unknown[]) => mockRunContactAiAssistFill(...args),
}))
vi.mock('./corp-butler/useContactCompanyMatch', async () => {
  const { ref } = await import('vue')
  return {
    useContactCompanyMatch: () => ({
      hint: ref('已识别公司'),
      hintVariant: ref('ok'),
      resultMode: ref('warn'),
      resultText: ref('注意重名公司'),
      suggestions: ref([{ name: '成都修茈科技有限公司' }]),
      showSuggestions: ref(true),
      matchUiUnlocked: ref(true),
      resetUi: vi.fn(),
      onCompanyInput: vi.fn(),
      onIndustryFocus: vi.fn(),
      onIndustryInput: vi.fn(),
      selectSuggestion: vi.fn(),
      getCompanyForSubmit: (value: string) => value.trim(),
    }),
  }
})
vi.mock('./composables/useStreamingTts', () => ({
  useStreamingTts: () => mockStreamingTts,
  ttsConfigFromPersonalSettings: (settings: unknown) => settings,
}))
vi.mock('./utils/personalSettings', () => ({
  loadPersonalSettings: () => ({ ttsVoiceName: '中文', ttsRate: 1 }),
}))
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    run: vi.fn(async () => undefined),
  },
}))

class FakeRecognition {
  static instances: FakeRecognition[] = []
  static startError: Error | null = null
  lang = ''
  interimResults = false
  continuous = false
  onresult: ((event: any) => void) | null = null
  onerror: ((event: any) => void) | null = null
  onend: (() => void) | null = null
  start = vi.fn(() => {
    if (FakeRecognition.startError) throw FakeRecognition.startError
  })
  stop = vi.fn(() => {
    this.onend?.()
  }, 15_000)
  constructor() {
    FakeRecognition.instances.push(this)
  }
}

beforeEach(() => {
  mockAgentStore.isOpen = false
  mockAgentStore.showPermissionDialog = false
  mockAgentStore.position = { x: 20, y: 20 }
  mockAgentStore.consentGiven = false
  mockAgentStore.isLoading = false
  Object.defineProperty(window, 'location', {
    value: { pathname: '/contact', host: 'example.test', protocol: 'https:' },
    configurable: true,
  })
  Object.defineProperty(window, 'matchMedia', {
    value: vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
    configurable: true,
  })
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn(async () => undefined) },
    configurable: true,
  })
  vi.stubGlobal('requestAnimationFrame', vi.fn((cb: FrameRequestCallback) => window.setTimeout(() => cb(0), 0)))
  vi.stubGlobal('cancelAnimationFrame', vi.fn((id: number) => window.clearTimeout(id)))
  vi.stubGlobal('SpeechRecognition', FakeRecognition)
  vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
  Object.defineProperty(window, 'speechSynthesis', {
    value: {
      getVoices: vi.fn(() => [{ name: '中文', lang: 'zh-CN' }, { name: 'English', lang: 'en-US' }]),
      onvoiceschanged: null,
    },
    configurable: true,
  })
})

afterEach(() => {
  mockRunIntakeTask.mockClear()
  mockHandleInput.mockClear()
  mockRunContactAiAssistFill.mockReset()
  mockStreamingTts.speak.mockClear()
  mockStreamingTts.stop.mockClear()
  mockAgentStore.openPanel.mockClear()
  mockAgentStore.grantConsent.mockClear()
  mockAgentStore.dismissLater.mockClear()
  mockAgentStore.savePosition.mockClear()
  mockAgentStore.addMessage.mockClear()
  mockAgentStore.updateLastMessage.mockClear()
  FakeRecognition.instances.length = 0
  FakeRecognition.startError = null
  document.body.innerHTML = ''
  document.documentElement.style.overflow = ''
  document.body.style.overflow = ''
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('floating corp and voice component coverage', () => {
  it('handles corp butler root consent, pending intake events, resize, and auto-open', async () => {
    vi.useFakeTimers()
    const { default: CorpButlerRoot } = await import('./corp-butler/CorpButlerRoot.vue')
    const wrapper = shallowMount(CorpButlerRoot, {
      global: {
        stubs: {
          Teleport: true,
          Transition: false,
          AgentPermissionDialog: { template: `<button class="agree" @click="$emit('agree')">agree</button>` },
          FloatingAgentBall: true,
          FloatingAgentPanel: true,
          CorpContactIntakeModal: true,
        },
      },
    })

    window.dispatchEvent(new CustomEvent('xc-corp-intake-assist', { detail: { message: '填表', prompt: '公司 CRM' } }))
    await wrapper.vm.$nextTick()
    expect(mockAgentStore.showPermissionDialog).toBe(true)

    mockAgentStore.consentGiven = true
    mockAgentStore.showPermissionDialog = false
    window.dispatchEvent(new CustomEvent('xc-corp-intake-assist', { detail: { message: '填表', prompt: '公司 CRM' } }))
    await wrapper.vm.$nextTick()
    expect(mockAgentStore.openPanel).toHaveBeenCalled()
    expect(mockRunIntakeTask).toHaveBeenCalledWith(expect.objectContaining({ payload: { prompt: '公司 CRM' } }))

    window.dispatchEvent(new CustomEvent('xc-corp-intake-assist', { detail: { filled: true } }))
    window.dispatchEvent(new Event('resize'))
    await vi.advanceTimersByTimeAsync(800)
    expect(mockAgentStore.savePosition).toHaveBeenCalled()
    expect(mockAgentStore.openPanel).toHaveBeenCalled()
    wrapper.unmount()
  }, 15_000)

  it('submits mobile contact intake modal success, validation, backend failure, and close guard', async () => {
    const modalState = await import('./corp-butler/useContactIntakeModal')
    modalState.contactIntakeModalOpen.value = true
    const { default: CorpContactIntakeModal } = await import('./components/floating-agent/CorpContactIntakeModal.vue')
    mockRunContactAiAssistFill.mockResolvedValueOnce({ ok: true, message: '已预填' })
    const wrapper = mount(CorpContactIntakeModal, {
      global: { stubs: { Teleport: true, Transition: false } },
    })

    await wrapper.find('#corp-intake-modal-company').setValue(' 修茈科技 ')
    await wrapper.find('#corp-intake-modal-system').setValue(' CRM ')
    await wrapper.find('form').trigger('submit')
    await Promise.resolve()
    await Promise.resolve()
    expect(mockRunContactAiAssistFill).toHaveBeenCalledWith('修茈科技', 'CRM')
    expect(mockAgentStore.addMessage).toHaveBeenCalledTimes(2)
    expect(mockAgentStore.updateLastMessage).toHaveBeenCalledWith(expect.objectContaining({ content: '已预填' }))
    expect(modalState.contactIntakeFillCompleted.value).toBe(true)

    modalState.contactIntakeModalOpen.value = true
    mockRunContactAiAssistFill.mockResolvedValueOnce({ ok: false, message: '缺少信息' })
    await wrapper.find('#corp-intake-modal-company').setValue('公司')
    await wrapper.find('#corp-intake-modal-system').setValue('ERP')
    await wrapper.find('form').trigger('submit')
    await Promise.resolve()
    await Promise.resolve()
    expect(wrapper.text()).toContain('缺少信息')

    mockRunContactAiAssistFill.mockRejectedValueOnce(new Error('network'))
    await wrapper.find('form').trigger('submit')
    await Promise.resolve()
    await Promise.resolve()
    expect(mockAgentStore.updateLastMessage).toHaveBeenCalledWith(expect.objectContaining({ content: '网络异常，请稍后重试。' }))

    wrapper.unmount()
  })

  it('renders message body markdown, binds copy buttons, and runs mermaid flush', async () => {
    vi.useFakeTimers()
    const { default: MessageBody } = await import('./components/workbench/MessageBody.vue')
    const wrapper = mount(MessageBody, {
      props: {
        streaming: true,
        content: '```ts\nconst a = 1\n```\n\n```mermaid\ngraph TD\nA-->B\n```',
      },
    })
    await vi.advanceTimersByTimeAsync(10)
    expect(wrapper.html()).toContain('msg-body__cursor')
    const copy = wrapper.find('.md-code__copy')
    if (copy.exists()) await copy.trigger('click')
    expect(navigator.clipboard.writeText).toHaveBeenCalled()
    await wrapper.setProps({ streaming: false, content: '```mermaid\ngraph TD\nA-->B\n```' })
    await vi.advanceTimersByTimeAsync(10)
    wrapper.unmount()
  })

  it('drives voice phone modal recognition, turn handling, mute, clear, and close', async () => {
    const { default: VoicePhoneModal } = await import('./components/workbench/VoicePhoneModal.vue')
    const onTurn = vi.fn(async () => 'AI 回复')
    const wrapper = mount(VoicePhoneModal, {
      props: { open: true, onTurn },
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('中文')

    await wrapper.find('.vp-orb').trigger('click')
    const rec = FakeRecognition.instances[0]
    expect(rec.start).toHaveBeenCalled()
    rec.onresult?.({ resultIndex: 0, results: [[{ transcript: '你好' }]] })
    rec.onend?.()
    await Promise.resolve()
    await Promise.resolve()
    expect(onTurn).toHaveBeenCalledWith('你好', expect.any(Array))
    expect(mockStreamingTts.speak).toHaveBeenCalledWith('AI 回复')

    await wrapper.findAll('.vp-btn--ghost')[1].trigger('click')
    expect(mockStreamingTts.stop).toHaveBeenCalled()
    await wrapper.findAll('.vp-btn--ghost')[0].trigger('click')
    expect(wrapper.text()).toContain('点中间圆球')

    await wrapper.setProps({ open: false })
    expect(mockStreamingTts.stop).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('covers voice modal recognition failures and fallback replies', async () => {
    const { default: VoicePhoneModal } = await import('./components/workbench/VoicePhoneModal.vue')
    vi.stubGlobal('SpeechRecognition', undefined)
    vi.stubGlobal('webkitSpeechRecognition', undefined)
    const unsupported = mount(VoicePhoneModal, {
      props: { open: true, onTurn: vi.fn() },
    })
    await unsupported.find('.vp-orb').trigger('click')
    expect(unsupported.text()).toContain('当前浏览器不支持语音识别')
    unsupported.unmount()

    vi.stubGlobal('SpeechRecognition', FakeRecognition)
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const startFail = mount(VoicePhoneModal, {
      props: { open: true, onTurn: vi.fn() },
    })
    FakeRecognition.startError = new Error('blocked')
    await startFail.find('.vp-orb').trigger('click')
    expect(startFail.text()).toContain('blocked')
    FakeRecognition.startError = null
    startFail.unmount()

    const blankTurn = vi.fn(async () => '   ')
    const failingTurn = vi.fn(async () => {
      throw new Error('ai down')
    })
    const wrapper = mount(VoicePhoneModal, {
      props: { open: true, onTurn: blankTurn },
    })
    await wrapper.find('.vp-orb').trigger('click')
    const noInterim = FakeRecognition.instances.at(-1)!
    noInterim.onend?.()
    await wrapper.find('.vp-orb').trigger('click')
    const rec = FakeRecognition.instances.at(-1)!
    rec.onerror?.({ error: 'no-speech' })
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('语音电话')
    rec.onresult?.({ resultIndex: 0, results: [[{ transcript: '' }]] })
    await wrapper.setProps({ onTurn: failingTurn })
    rec.onresult?.({ resultIndex: 0, results: [[{ transcript: '失败测试' }]] })
    rec.onend?.()
    await Promise.resolve()
    await Promise.resolve()
    expect(wrapper.text()).toContain('ai down')

    await wrapper.setProps({ onTurn: blankTurn })
    await wrapper.find('.vp-orb').trigger('click')
    const fallbackRec = FakeRecognition.instances.at(-1)!
    fallbackRec.onresult?.({ resultIndex: 0, results: [[{ transcript: '空回复' }]] })
    fallbackRec.onend?.()
    await Promise.resolve()
    await Promise.resolve()
    expect(mockStreamingTts.speak).toHaveBeenCalledWith('（AI 没有给出回复）')
    wrapper.unmount()
  })

  it('covers voice modal playback, listening stop, synthesis fallback, and mute reset', async () => {
    const { default: VoicePhoneModal } = await import('./components/workbench/VoicePhoneModal.vue')
    let resolveSpeak: (() => void) | undefined
    mockStreamingTts.speak.mockImplementationOnce(() => new Promise<void>((resolve) => {
      resolveSpeak = resolve
    }))
    const wrapper = mount(VoicePhoneModal, {
      props: { open: true, onTurn: vi.fn(async () => '长回复') },
    })
    await wrapper.find('.vp-orb').trigger('click')
    const rec = FakeRecognition.instances.at(-1)!
    rec.onresult?.({ resultIndex: 0, results: [[{ transcript: '请回答' }]] })
    rec.onend?.()
    await Promise.resolve()
    await Promise.resolve()
    await wrapper.find('.vp-orb').trigger('click')
    expect(mockStreamingTts.stop).toHaveBeenCalled()
    resolveSpeak?.()
    await Promise.resolve()

    const stopWrapper = mount(VoicePhoneModal, {
      props: { open: true, onTurn: vi.fn(async () => 'ok') },
    })
    await stopWrapper.find('.vp-orb').trigger('click')
    const listening = FakeRecognition.instances.at(-1)!
    await stopWrapper.find('.vp-orb').trigger('click')
    expect(listening.stop).toHaveBeenCalled()
    stopWrapper.unmount()

    mockStreamingTts.speak.mockImplementationOnce(() => new Promise<void>(() => undefined))
    rec.onresult?.({ resultIndex: 0, results: [[{ transcript: '静音测试' }]] })
    rec.onend?.()
    await Promise.resolve()
    await Promise.resolve()
    await wrapper.findAll('.vp-btn--ghost')[1].trigger('click')
    expect(mockStreamingTts.stop).toHaveBeenCalled()
    wrapper.unmount()

    Object.defineProperty(window, 'speechSynthesis', {
      value: undefined,
      configurable: true,
    })
    const noSynth = mount(VoicePhoneModal, {
      props: { open: true, onTurn: vi.fn() },
    })
    await noSynth.vm.$nextTick()
    expect(noSynth.text()).not.toContain('中文 (zh-CN)')
    noSynth.unmount()
  })
})
