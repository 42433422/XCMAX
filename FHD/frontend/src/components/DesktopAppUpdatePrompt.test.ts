import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { defineComponent, nextTick } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'

const updateListeners: Array<(event: unknown) => void> = []

const desktopApi = {
  checkForUpdates: vi.fn().mockResolvedValue({}),
  getUpdateStatus: vi.fn().mockResolvedValue(null),
  downloadUpdate: vi.fn().mockResolvedValue({}),
  installUpdate: vi.fn().mockResolvedValue(undefined),
  onUpdateEvent: vi.fn((cb: (event: unknown) => void) => {
    updateListeners.push(cb)
    return () => {
      const idx = updateListeners.indexOf(cb)
      if (idx >= 0) updateListeners.splice(idx, 1)
    }
  }),
}

vi.mock('@/utils/desktopShell', () => ({
  isDesktopShell: () => true,
}))

vi.mock('@/components/Modal.vue', () => ({
  default: {
    name: 'Modal',
    props: ['modelValue', 'title', 'maxWidth'],
    emits: ['update:modelValue'],
    template: `<div v-if="modelValue" class="modal-stub"><div class="modal-stub-title">{{ title }}</div><slot /><slot name="footer" /></div>`,
  },
}))

import DesktopAppUpdatePrompt from './DesktopAppUpdatePrompt.vue'
import { __resetDesktopAppUpdaterForTest } from '@/composables/useDesktopAppUpdater'

function emitUpdate(type: string, data: unknown = {}) {
  for (const cb of updateListeners) cb({ type, data })
}

describe('DesktopAppUpdatePrompt', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    updateListeners.length = 0
    sessionStorage.clear()
    __resetDesktopAppUpdaterForTest()
    ;(window as Window & { xcagiDesktop?: unknown }).xcagiDesktop = desktopApi
  })

  afterEach(() => {
    delete (window as Window & { xcagiDesktop?: unknown }).xcagiDesktop
  })

  function mountPrompt() {
    const Host = defineComponent({
      components: { DesktopAppUpdatePrompt },
      template: '<DesktopAppUpdatePrompt />',
    })
    return mount(Host)
  }

  it('shows corner chip when update is available', async () => {
    const wrapper = mountPrompt()
    await flushPromises()
    emitUpdate('update-available', {
      version: '1.0.0',
      buildSha: 'abcdef123456',
      releaseNotes: '- fix mac OTA\n- cursor-style prompt',
    })
    await nextTick()
    expect(wrapper.find('.desktop-update-chip').exists()).toBe(true)
    expect(wrapper.text()).toContain('可更新 1.0.0')
  })

  it('opens notes modal and downloads only after click', async () => {
    const wrapper = mountPrompt()
    await flushPromises()
    emitUpdate('update-available', {
      version: '1.0.0',
      releaseNotes: '• 更新桌面壳\n• 重新加载进入新版本',
    })
    await nextTick()
    expect(desktopApi.downloadUpdate).not.toHaveBeenCalled()
    await wrapper.find('.desktop-update-chip').trigger('click')
    expect(wrapper.find('.modal-stub').exists()).toBe(true)
    expect(wrapper.text()).toContain('更新桌面壳')
    const downloadBtn = wrapper.findAll('button').find((b) => b.text().includes('下载更新'))!
    await downloadBtn.trigger('click')
    await flushPromises()
    expect(desktopApi.downloadUpdate).toHaveBeenCalledTimes(1)
  })

  it('installs after download completes', async () => {
    const wrapper = mountPrompt()
    await flushPromises()
    emitUpdate('update-available', { version: '1.0.0', releaseNotes: 'notes' })
    await nextTick()
    await wrapper.find('.desktop-update-chip').trigger('click')
    emitUpdate('update-downloaded', { version: '1.0.0' })
    await nextTick()
    const installBtn = wrapper.findAll('button').find((b) => b.text().includes('更新并重新加载'))!
    await installBtn.trigger('click')
    await flushPromises()
    expect(desktopApi.installUpdate).toHaveBeenCalledTimes(1)
  })
})
