import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  getTtsStatus: vi.fn(),
  onTtsStatusChange: vi.fn(),
  ensureVoicesLoaded: vi.fn().mockResolvedValue(undefined),
  setEngineMode: vi.fn(),
  dismissBanner: vi.fn(),
  isBannerDismissed: vi.fn().mockReturnValue(false),
  startOfflineDownload: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/utils/tts', () => ({
  getTtsStatus: mocks.getTtsStatus,
  onTtsStatusChange: mocks.onTtsStatusChange,
  ensureVoicesLoaded: mocks.ensureVoicesLoaded,
  setEngineMode: mocks.setEngineMode,
  dismissBanner: mocks.dismissBanner,
  isBannerDismissed: mocks.isBannerDismissed,
  startOfflineDownload: mocks.startOfflineDownload,
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    info: vi.fn(() => ({ close: vi.fn() })),
    success: vi.fn(() => ({ close: vi.fn() })),
    warning: vi.fn(() => ({ close: vi.fn() })),
    error: vi.fn(() => ({ close: vi.fn() })),
  },
  ElDialog: {
    name: 'ElDialog',
    props: ['modelValue', 'title', 'width', 'appendToBody'],
    emits: ['update:modelValue'],
    template: '<div v-if="modelValue" class="el-dialog-stub"><slot /></div>',
  },
}))

vi.mock('@/api', () => ({
  api: {
    post: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    data: unknown
    constructor(message: string, data?: unknown) {
      super(message)
      this.data = data
    }
  },
}))

import TtsSetupBanner from './TtsSetupBanner.vue'
import { api } from '@/api'

const getTtsStatus = mocks.getTtsStatus
const onTtsStatusChange = mocks.onTtsStatusChange
const setEngineMode = mocks.setEngineMode
const dismissBanner = mocks.dismissBanner
const isBannerDismissed = mocks.isBannerDismissed
const startOfflineDownload = mocks.startOfflineDownload

describe('TtsSetupBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default: no yunxi, no neural, system voice, online engine
    getTtsStatus.mockReturnValue({
      effectiveEngine: 'system',
      offlineReady: false,
      offlineLoading: false,
      offlineProgress: 0,
      engineMode: 'system',
      yunxiAvailable: false,
      neuralAvailable: false,
      anyChineseLocal: false,
      systemVoice: 'Browser Default',
      onlineVoiceId: 'zh-CN-XiaoxiaoNeural',
    })
    isBannerDismissed.mockReturnValue(false)
  })

  function mountBanner() {
    return mount(TtsSetupBanner)
  }

  it('does not render when banner is dismissed', async () => {
    isBannerDismissed.mockReturnValue(true)
    const wrapper = mountBanner()
    await flushPromises()
    expect(wrapper.find('.tts-banner').exists()).toBe(false)
  })

  it('renders banner when yunxi is not available', async () => {
    const wrapper = mountBanner()
    await flushPromises()
    expect(wrapper.find('.tts-banner').exists()).toBe(true)
  })

  it('shows offline progress when downloading', async () => {
    getTtsStatus.mockReturnValue({
      effectiveEngine: 'offline',
      offlineReady: false,
      offlineLoading: true,
      offlineProgress: 0.5,
      engineMode: 'offline',
      yunxiAvailable: false,
      neuralAvailable: false,
      anyChineseLocal: false,
      systemVoice: 'Browser Default',
      onlineVoiceId: 'zh-CN-XiaoxiaoNeural',
    })
    const wrapper = mountBanner()
    await flushPromises()
    expect(wrapper.find('.tts-banner').exists()).toBe(true)
    expect(wrapper.text()).toContain('正在下载离线语音包')
    expect(wrapper.text()).toContain('50%')
  })

  it('shows offline ready message when offline engine is active', async () => {
    getTtsStatus.mockReturnValue({
      effectiveEngine: 'offline',
      offlineReady: true,
      offlineLoading: false,
      offlineProgress: 1,
      engineMode: 'offline',
      yunxiAvailable: false,
      neuralAvailable: false,
      anyChineseLocal: false,
      systemVoice: 'Browser Default',
      onlineVoiceId: 'zh-CN-XiaoxiaoNeural',
    })
    const wrapper = mountBanner()
    await flushPromises()
    expect(wrapper.text()).toContain('已启用离线语音')
  })

  it('shows online engine message when online engine is active', async () => {
    getTtsStatus.mockReturnValue({
      effectiveEngine: 'online',
      offlineReady: false,
      offlineLoading: false,
      offlineProgress: 0,
      engineMode: 'online',
      yunxiAvailable: false,
      neuralAvailable: false,
      anyChineseLocal: false,
      systemVoice: 'Browser Default',
      onlineVoiceId: 'zh-CN-YunxiNeural',
    })
    const wrapper = mountBanner()
    await flushPromises()
    expect(wrapper.text()).toContain('已启用在线语音')
    expect(wrapper.text()).toContain('zh-CN-YunxiNeural')
  })

  it('shows yunxi available message when yunxi is available', async () => {
    getTtsStatus.mockReturnValue({
      effectiveEngine: 'system',
      offlineReady: false,
      offlineLoading: false,
      offlineProgress: 0,
      engineMode: 'system',
      yunxiAvailable: true,
      neuralAvailable: true,
      anyChineseLocal: true,
      systemVoice: 'Microsoft Yunxi',
      onlineVoiceId: 'zh-CN-YunxiNeural',
    })
    const wrapper = mountBanner()
    await flushPromises()
    // When yunxi is available, banner should not be visible
    expect(wrapper.find('.tts-banner').exists()).toBe(false)
  })

  it('shows neural available message when neural is available but not yunxi', async () => {
    getTtsStatus.mockReturnValue({
      effectiveEngine: 'system',
      offlineReady: false,
      offlineLoading: false,
      offlineProgress: 0,
      engineMode: 'system',
      yunxiAvailable: false,
      neuralAvailable: true,
      anyChineseLocal: false,
      systemVoice: 'Microsoft Xiaoxiao',
      onlineVoiceId: 'zh-CN-XiaoxiaoNeural',
    })
    const wrapper = mountBanner()
    await flushPromises()
    expect(wrapper.text()).toContain('已启用系统神经网络语音')
  })

  it('shows default message when no voice is available', async () => {
    getTtsStatus.mockReturnValue({
      effectiveEngine: 'system',
      offlineReady: false,
      offlineLoading: false,
      offlineProgress: 0,
      engineMode: 'system',
      yunxiAvailable: false,
      neuralAvailable: false,
      anyChineseLocal: false,
      systemVoice: '',
      onlineVoiceId: 'zh-CN-XiaoxiaoNeural',
    })
    const wrapper = mountBanner()
    await flushPromises()
    expect(wrapper.text()).toContain('没检测到云希/晓晓')
  })

  it('calls setEngineMode to offline when download offline button clicked', async () => {
    const wrapper = mountBanner()
    await flushPromises()
    const downloadBtn = wrapper.findAll('button').find((b) => b.text().includes('下载离线包'))
    expect(downloadBtn).toBeTruthy()
    await downloadBtn!.trigger('click')
    await flushPromises()
    expect(startOfflineDownload).toHaveBeenCalled()
    expect(setEngineMode).toHaveBeenCalledWith('offline')
  })

  it('calls setEngineMode to online when use online button clicked', async () => {
    const wrapper = mountBanner()
    await flushPromises()
    const onlineBtn = wrapper.findAll('button').find((b) => b.text().includes('在线语音'))
    expect(onlineBtn).toBeTruthy()
    await onlineBtn!.trigger('click')
    expect(setEngineMode).toHaveBeenCalledWith('online')
  })

  it('calls setEngineMode to offline when use offline button clicked', async () => {
    getTtsStatus.mockReturnValue({
      effectiveEngine: 'online',
      offlineReady: true,
      offlineLoading: false,
      offlineProgress: 1,
      engineMode: 'online',
      yunxiAvailable: false,
      neuralAvailable: false,
      anyChineseLocal: false,
      systemVoice: 'Browser Default',
      onlineVoiceId: 'zh-CN-YunxiNeural',
    })
    const wrapper = mountBanner()
    await flushPromises()
    const offlineBtn = wrapper.findAll('button').find((b) => b.text().includes('切到离线语音'))
    expect(offlineBtn).toBeTruthy()
    await offlineBtn!.trigger('click')
    expect(setEngineMode).toHaveBeenCalledWith('offline')
  })

  it('calls setEngineMode to system when use system button clicked', async () => {
    getTtsStatus.mockReturnValue({
      effectiveEngine: 'online',
      offlineReady: false,
      offlineLoading: false,
      offlineProgress: 0,
      engineMode: 'online',
      yunxiAvailable: false,
      neuralAvailable: false,
      anyChineseLocal: false,
      systemVoice: 'Browser Default',
      onlineVoiceId: 'zh-CN-YunxiNeural',
    })
    const wrapper = mountBanner()
    await flushPromises()
    const systemBtn = wrapper.findAll('button').find((b) => b.text().includes('切到系统语音'))
    expect(systemBtn).toBeTruthy()
    await systemBtn!.trigger('click')
    expect(setEngineMode).toHaveBeenCalledWith('system')
  })

  it('calls dismissBanner when close button clicked', async () => {
    const wrapper = mountBanner()
    await flushPromises()
    const closeBtn = wrapper.findAll('button').find((b) => b.text().includes('不再提示'))
    expect(closeBtn).toBeTruthy()
    await closeBtn!.trigger('click')
    expect(dismissBanner).toHaveBeenCalled()
  })

  it('shows install windows voice button when yunxi not available', async () => {
    const wrapper = mountBanner()
    await flushPromises()
    const installBtn = wrapper.findAll('button').find((b) => b.text().includes('一键安装系统云希'))
    expect(installBtn).toBeTruthy()
  })

  it('calls api.post when install windows voice button clicked', async () => {
    const wrapper = mountBanner()
    await flushPromises()
    const installBtn = wrapper.findAll('button').find((b) => b.text().includes('一键安装系统云希'))
    expect(installBtn).toBeTruthy()
    vi.mocked(api.post).mockResolvedValue({ success: true, message: '已发起安装' })
    await installBtn!.trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenCalledWith('/api/tts/install-system-voice', {})
  })

  it('shows ps dialog when install fails', async () => {
    const wrapper = mountBanner()
    await flushPromises()
    const installBtn = wrapper.findAll('button').find((b) => b.text().includes('一键安装系统云希'))
    vi.mocked(api.post).mockRejectedValue(new Error('Permission denied'))
    await installBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.el-dialog-stub').exists()).toBe(true)
  })

  it('renders ps command in dialog', async () => {
    const wrapper = mountBanner()
    await flushPromises()
    const installBtn = wrapper.findAll('button').find((b) => b.text().includes('一键安装系统云希'))
    vi.mocked(api.post).mockRejectedValue(new Error('Permission denied'))
    await installBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Get-WindowsCapability')
  })

  it('shows downloading state when offline is loading', async () => {
    getTtsStatus.mockReturnValue({
      effectiveEngine: 'offline',
      offlineReady: false,
      offlineLoading: true,
      offlineProgress: 0.3,
      engineMode: 'offline',
      yunxiAvailable: false,
      neuralAvailable: false,
      anyChineseLocal: false,
      systemVoice: 'Browser Default',
      onlineVoiceId: 'zh-CN-XiaoxiaoNeural',
    })
    const wrapper = mountBanner()
    await flushPromises()
    expect(wrapper.find('.tts-banner.is-downloading').exists()).toBe(true)
  })

  it('shows progress bar with correct width', async () => {
    getTtsStatus.mockReturnValue({
      effectiveEngine: 'offline',
      offlineReady: false,
      offlineLoading: true,
      offlineProgress: 0.75,
      engineMode: 'offline',
      yunxiAvailable: false,
      neuralAvailable: false,
      anyChineseLocal: false,
      systemVoice: 'Browser Default',
      onlineVoiceId: 'zh-CN-XiaoxiaoNeural',
    })
    const wrapper = mountBanner()
    await flushPromises()
    const progressBar = wrapper.find('.tts-progress-bar')
    expect(progressBar.exists()).toBe(true)
    expect(progressBar.attributes('style')).toContain('width: 75%')
  })

  it('unsubscribes from tts status change on unmount', async () => {
    const unsubscribe = vi.fn()
    onTtsStatusChange.mockReturnValue(unsubscribe)
    const wrapper = mountBanner()
    await flushPromises()
    wrapper.unmount()
    expect(unsubscribe).toHaveBeenCalled()
  })
})
