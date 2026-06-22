import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

const { ttsStatusRef, ttsMocks, apiPost, elMessageMocks, ApiErrorImpl } = vi.hoisted(() => {
  const ttsStatusRef = {
    engineMode: 'system' as string,
    effectiveEngine: 'system' as string,
    onlineVoiceId: 'zh-CN-XiaoxiaoNeural',
    systemVoice: null as string | null,
    yunxiAvailable: false,
    neuralAvailable: false,
    anyChineseLocal: false,
    offlineReady: false,
    offlineLoading: false,
    offlineProgress: 0,
    bannerDismissed: false,
  }
  const ttsMocks = {
    getTtsStatus: vi.fn(() => ({ ...ttsStatusRef })),
    onTtsStatusChange: vi.fn(() => vi.fn()),
    ensureVoicesLoaded: vi.fn(() => Promise.resolve([])),
    setEngineMode: vi.fn(),
    dismissBanner: vi.fn(),
    isBannerDismissed: vi.fn(() => false),
    startOfflineDownload: vi.fn(() => Promise.resolve()),
  }
  const apiPost = vi.fn()
  const elMessageMocks = {
    info: vi.fn(() => ({ close: vi.fn() })),
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  }
  class ApiErrorImpl extends Error {
    data: unknown
    constructor(message: string, data: unknown) {
      super(message)
      this.name = 'ApiError'
      this.data = data
    }
  }
  return { ttsStatusRef, ttsMocks, apiPost, elMessageMocks, ApiErrorImpl }
})

vi.mock('@/utils/tts', () => ttsMocks)
vi.mock('@/api', () => ({
  api: { post: apiPost },
  ApiError: ApiErrorImpl,
}))
vi.mock('element-plus', () => ({
  ElMessage: elMessageMocks,
  ElDialog: {
    name: 'ElDialog',
    props: ['modelValue', 'title', 'width', 'appendToBody'],
    emits: ['update:modelValue'],
    template: '<div v-if="modelValue" class="el-dialog-stub"><slot /></div>',
  },
}))

import TtsSetupBanner from '@/components/TtsSetupBanner.vue'

function setStatus(overrides = {}) {
  Object.assign(ttsStatusRef, overrides)
  ttsMocks.getTtsStatus.mockReturnValue({ ...ttsStatusRef })
}

function mountComponent() {
  return mount(TtsSetupBanner, {
    global: {
      stubs: {
        ElDialog: {
          name: 'ElDialog',
          props: ['modelValue', 'title', 'width', 'appendToBody'],
          emits: ['update:modelValue'],
          template: '<div v-if="modelValue" class="el-dialog-stub"><slot /></div>',
        },
      },
    },
  })
}

describe('TtsSetupBanner.coverage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    setStatus({
      engineMode: 'system',
      effectiveEngine: 'system',
      onlineVoiceId: 'zh-CN-XiaoxiaoNeural',
      systemVoice: null,
      yunxiAvailable: false,
      neuralAvailable: false,
      anyChineseLocal: false,
      offlineReady: false,
      offlineLoading: false,
      offlineProgress: 0,
      bannerDismissed: false,
    })
    ttsMocks.isBannerDismissed.mockReturnValue(false)
    ttsMocks.ensureVoicesLoaded.mockResolvedValue([])
    ttsMocks.startOfflineDownload.mockResolvedValue(undefined)
    apiPost.mockResolvedValue({ success: true, message: 'ok' })
  })

  it('renders banner when visible (no yunxi, not dismissed)', async () => {
    const wrapper = mountComponent()
    await nextTick()
    expect(wrapper.find('.tts-banner').exists()).toBe(true)
  })

  it('does not render banner when dismissed', async () => {
    ttsMocks.isBannerDismissed.mockReturnValue(true)
    const wrapper = mountComponent()
    await nextTick()
    expect(wrapper.find('.tts-banner').exists()).toBe(false)
  })

  it('renders banner when downloading', async () => {
    setStatus({ offlineLoading: true, offlineProgress: 0.5 })
    const wrapper = mountComponent()
    await nextTick()
    expect(wrapper.find('.tts-banner').exists()).toBe(true)
    expect(wrapper.find('.tts-banner').classes()).toContain('is-downloading')
  })

  it('renders banner when engineMode is online', async () => {
    setStatus({ engineMode: 'online', effectiveEngine: 'online' })
    const wrapper = mountComponent()
    await nextTick()
    expect(wrapper.find('.tts-banner').exists()).toBe(true)
  })

  it('hides banner when yunxiAvailable', async () => {
    setStatus({ yunxiAvailable: true })
    const wrapper = mountComponent()
    await nextTick()
    expect(wrapper.find('.tts-banner').exists()).toBe(false)
  })

  it('hides banner when anyChineseLocal', async () => {
    setStatus({ anyChineseLocal: true })
    const wrapper = mountComponent()
    await nextTick()
    expect(wrapper.find('.tts-banner').exists()).toBe(false)
  })

  it('renders downloading progress text', async () => {
    setStatus({ offlineLoading: true, offlineProgress: 0.6 })
    const wrapper = mountComponent()
    await nextTick()
    expect(wrapper.text()).toContain('60%')
    expect(wrapper.find('.tts-progress-bar').exists()).toBe(true)
  })

  it('renders offline ready state when effectiveEngine offline and offlineReady', async () => {
    setStatus({ effectiveEngine: 'offline', offlineReady: true })
    const wrapper = mountComponent()
    await nextTick()
    expect(wrapper.text()).toContain('已启用离线语音')
  })

  it('renders online engine state', async () => {
    setStatus({ effectiveEngine: 'online', engineMode: 'online' })
    const wrapper = mountComponent()
    await nextTick()
    expect(wrapper.text()).toContain('已启用在线语音')
    expect(wrapper.text()).toContain('zh-CN-XiaoxiaoNeural')
  })

  it('renders neural available state', async () => {
    setStatus({ neuralAvailable: true, systemVoice: 'Huihui' })
    const wrapper = mountComponent()
    await nextTick()
    expect(wrapper.text()).toContain('已启用系统神经网络语音')
  })

  it('renders no neural voice state', async () => {
    const wrapper = mountComponent()
    await nextTick()
    expect(wrapper.text()).toContain('没检测到云希/晓晓')
  })

  it('renders no neural voice state with default system voice', async () => {
    setStatus({ systemVoice: null })
    const wrapper = mountComponent()
    await nextTick()
    expect(wrapper.text()).toContain('浏览器默认')
  })

  it('installWindowsVoice calls api.post and shows success on success', async () => {
    const wrapper = mountComponent()
    await nextTick()
    const btn = wrapper.find('.tts-btn-primary')
    expect(btn.text()).toContain('一键安装系统云希')
    await btn.trigger('click')
    await nextTick()
    expect(apiPost).toHaveBeenCalledWith('/api/tts/install-system-voice', {})
    expect(elMessageMocks.success).toHaveBeenCalled()
  })

  it('installWindowsVoice falls back to ps dialog when success false', async () => {
    apiPost.mockResolvedValue({ success: false, message: '失败原因' })
    const wrapper = mountComponent()
    await nextTick()
    await wrapper.find('.tts-btn-primary').trigger('click')
    await nextTick()
    expect(elMessageMocks.warning).toHaveBeenCalledWith(expect.stringContaining('失败原因'))
    expect(wrapper.find('.el-dialog-stub').exists()).toBe(true)
  })

  it('installWindowsVoice handles ApiError with server message', async () => {
    const err = new ApiErrorImpl('boom', { message: '后端错误说明' })
    apiPost.mockRejectedValue(err)
    const wrapper = mountComponent()
    await nextTick()
    await wrapper.find('.tts-btn-primary').trigger('click')
    await nextTick()
    expect(elMessageMocks.warning).toHaveBeenCalledWith('后端错误说明')
    expect(wrapper.find('.el-dialog-stub').exists()).toBe(true)
  })

  it('installWindowsVoice handles generic Error', async () => {
    apiPost.mockRejectedValue(new Error('网络错误'))
    const wrapper = mountComponent()
    await nextTick()
    await wrapper.find('.tts-btn-primary').trigger('click')
    await nextTick()
    expect(elMessageMocks.warning).toHaveBeenCalledWith(expect.stringContaining('网络错误'))
    expect(wrapper.find('.el-dialog-stub').exists()).toBe(true)
  })

  it('installWindowsVoice handles non-Error throw', async () => {
    apiPost.mockRejectedValue('string error')
    const wrapper = mountComponent()
    await nextTick()
    await wrapper.find('.tts-btn-primary').trigger('click')
    await nextTick()
    expect(elMessageMocks.warning).toHaveBeenCalledWith(expect.stringContaining('string error'))
  })

  it('installWindowsVoice does nothing when already installing', async () => {
    let resolveInstall!: (v: any) => void
    apiPost.mockReturnValueOnce(new Promise((r) => { resolveInstall = r }))
    const wrapper = mountComponent()
    await nextTick()
    const btn = wrapper.find('.tts-btn-primary')
    await btn.trigger('click')
    await nextTick()
    expect(btn.text()).toContain('等待管理员授权')
    apiPost.mockClear()
    await btn.trigger('click')
    await nextTick()
    expect(apiPost).not.toHaveBeenCalled()
    resolveInstall({ success: true })
    await nextTick()
  })

  it('copyPs copies command and shows success', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    const wrapper = mountComponent()
    await nextTick()
    apiPost.mockResolvedValue({ success: false })
    await wrapper.find('.tts-btn-primary').trigger('click')
    await nextTick()
    const copyBtn = wrapper.find('.el-dialog-stub .tts-btn-primary')
    await copyBtn.trigger('click')
    await nextTick()
    expect(writeText).toHaveBeenCalled()
    expect(elMessageMocks.success).toHaveBeenCalled()
  })

  it('copyPs shows warning when clipboard fails', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'))
    Object.assign(navigator, { clipboard: { writeText } })
    const wrapper = mountComponent()
    await nextTick()
    apiPost.mockResolvedValue({ success: false })
    await wrapper.find('.tts-btn-primary').trigger('click')
    await nextTick()
    const copyBtn = wrapper.find('.el-dialog-stub .tts-btn-primary')
    await copyBtn.trigger('click')
    await nextTick()
    expect(elMessageMocks.warning).toHaveBeenCalledWith('复制失败，请手动选中命令复制')
  })

  it('downloadOffline starts download and switches to offline', async () => {
    setStatus({ offlineReady: false })
    const wrapper = mountComponent()
    await nextTick()
    const downloadBtn = wrapper.findAll('.tts-btn').find((b) => b.text().includes('下载离线包'))
    expect(downloadBtn).toBeTruthy()
    await downloadBtn!.trigger('click')
    await nextTick()
    expect(ttsMocks.startOfflineDownload).toHaveBeenCalled()
    expect(ttsMocks.setEngineMode).toHaveBeenCalledWith('offline')
    expect(elMessageMocks.success).toHaveBeenCalled()
  })

  it('downloadOffline shows error on failure', async () => {
    ttsMocks.startOfflineDownload.mockRejectedValue(new Error('下载失败原因'))
    const wrapper = mountComponent()
    await nextTick()
    const downloadBtn = wrapper.findAll('.tts-btn').find((b) => b.text().includes('下载离线包'))
    await downloadBtn!.trigger('click')
    await nextTick()
    expect(elMessageMocks.error).toHaveBeenCalledWith(expect.stringContaining('下载失败原因'))
  })

  it('downloadOffline shows error on non-Error throw', async () => {
    ttsMocks.startOfflineDownload.mockRejectedValue('boom')
    const wrapper = mountComponent()
    await nextTick()
    const downloadBtn = wrapper.findAll('.tts-btn').find((b) => b.text().includes('下载离线包'))
    await downloadBtn!.trigger('click')
    await nextTick()
    expect(elMessageMocks.error).toHaveBeenCalledWith(expect.stringContaining('boom'))
  })

  it('useOffline switches engine to offline', async () => {
    setStatus({ effectiveEngine: 'system', offlineReady: true })
    const wrapper = mountComponent()
    await nextTick()
    const btn = wrapper.findAll('.tts-btn').find((b) => b.text().includes('切到离线语音'))
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await nextTick()
    expect(ttsMocks.setEngineMode).toHaveBeenCalledWith('offline')
    expect(elMessageMocks.success).toHaveBeenCalled()
  })

  it('useOnline switches engine to online', async () => {
    setStatus({ engineMode: 'system', effectiveEngine: 'system' })
    const wrapper = mountComponent()
    await nextTick()
    const btn = wrapper.findAll('.tts-btn').find((b) => b.text().includes('在线语音'))
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await nextTick()
    expect(ttsMocks.setEngineMode).toHaveBeenCalledWith('online')
    expect(elMessageMocks.success).toHaveBeenCalled()
  })

  it('useSystem switches engine to system when online', async () => {
    setStatus({ engineMode: 'online', effectiveEngine: 'online' })
    const wrapper = mountComponent()
    await nextTick()
    const btn = wrapper.findAll('.tts-btn').find((b) => b.text().includes('切到系统语音'))
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await nextTick()
    expect(ttsMocks.setEngineMode).toHaveBeenCalledWith('system')
    expect(elMessageMocks.success).toHaveBeenCalled()
  })

  it('useSystem switches to system when offline and yunxi available', async () => {
    setStatus({ engineMode: 'online', effectiveEngine: 'offline', offlineReady: true, yunxiAvailable: true })
    const wrapper = mountComponent()
    await nextTick()
    const btn = wrapper.findAll('.tts-btn').find((b) => b.text().includes('切到系统云希'))
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await nextTick()
    expect(ttsMocks.setEngineMode).toHaveBeenCalledWith('system')
  })

  it('close dismisses banner', async () => {
    const wrapper = mountComponent()
    await nextTick()
    const closeBtn = wrapper.findAll('.tts-btn').find((b) => b.text().includes('不再提示'))
    expect(closeBtn).toBeTruthy()
    await closeBtn!.trigger('click')
    await nextTick()
    expect(ttsMocks.dismissBanner).toHaveBeenCalled()
  })

  it('onMounted subscribes to status changes and loads voices', async () => {
    mountComponent()
    await nextTick()
    expect(ttsMocks.onTtsStatusChange).toHaveBeenCalled()
    expect(ttsMocks.ensureVoicesLoaded).toHaveBeenCalled()
  })

  it('onBeforeUnmount unsubscribes', async () => {
    const unsubscribe = vi.fn()
    ttsMocks.onTtsStatusChange.mockReturnValueOnce(unsubscribe)
    const wrapper = mountComponent()
    await nextTick()
    wrapper.unmount()
    expect(unsubscribe).toHaveBeenCalled()
  })

  it('refresh callback updates status on tts change', async () => {
    const wrapper = mountComponent()
    await nextTick()
    const refreshCb = ttsMocks.onTtsStatusChange.mock.calls[0][0] as () => void
    setStatus({ yunxiAvailable: true })
    refreshCb()
    await nextTick()
    expect(wrapper.find('.tts-banner').exists()).toBe(false)
  })

  it('downloading computed reflects offlineLoading', async () => {
    setStatus({ offlineLoading: true, offlineProgress: 0.3 })
    const wrapper = mountComponent()
    await nextTick()
    expect(wrapper.find('.tts-banner').classes()).toContain('is-downloading')
    expect(wrapper.text()).toContain('⏬')
  })

  it('shows installing text when installing', async () => {
    let resolveInstall!: (v: any) => void
    apiPost.mockReturnValueOnce(new Promise((r) => { resolveInstall = r }))
    const wrapper = mountComponent()
    await nextTick()
    const btn = wrapper.find('.tts-btn-primary')
    await btn.trigger('click')
    await nextTick()
    expect(btn.text()).toContain('等待管理员授权')
    resolveInstall({ success: true })
    await nextTick()
  })
})
