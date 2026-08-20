import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('qrcode', () => ({
  default: {
    toDataURL: vi.fn(async () => 'data:image/png;base64,fakeqr'),
  },
}))

const mockApiFetch = vi.fn()
vi.mock('@/utils/apiBase', () => ({
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
}))

const mockLoadDesktopPairingPayload = vi.fn()
vi.mock('@/api/mobilePairing', () => ({
  buildPairingQrText: () => 'qr-text',
  fetchHostDiscoverHint: vi.fn().mockResolvedValue({}),
  issueMobilePairing: vi.fn().mockResolvedValue({
    host: '127.0.0.1',
    port: 5000,
    nonce: 'n1',
    shortCode: '123456',
    exp: Math.floor(Date.now() / 1000) + 300,
  }),
  loadDesktopPairingPayload: (...args: unknown[]) => mockLoadDesktopPairingPayload(...args),
  resolvePairingHost: () => '127.0.0.1',
  resolvePairingPortHint: () => 5000,
}))

import MobilePairingQrCard from './MobilePairingQrCard.vue'

function jsonRes(body: unknown, ok = true) {
  return { ok, json: async () => body } as Response
}

describe('MobilePairingQrCard.vue', () => {
  beforeEach(() => {
    mockApiFetch.mockReset()
    mockLoadDesktopPairingPayload.mockReset()
    mockLoadDesktopPairingPayload.mockResolvedValue(null) // 走 issueMobilePairing 兜底分支
  })

  it('shows a loading status before the pairing-status request resolves', async () => {
    mockApiFetch.mockReturnValue(new Promise(() => {})) // never resolves during assertion
    const wrapper = mount(MobilePairingQrCard)
    await flushPromises()
    expect(wrapper.text()).toContain('正在查询连接状态…')
  })

  it('shows "尚未绑定手机" hint when not paired', async () => {
    mockApiFetch.mockResolvedValue(jsonRes({ paired: false, mobileUsername: '', lastRelaySyncAt: 0 }))
    const wrapper = mount(MobilePairingQrCard)
    await flushPromises()
    expect(wrapper.text()).toContain('尚未绑定手机')
    expect(wrapper.find('.mobile-pairing__status--pending').exists()).toBe(true)
  })

  it('shows connected status with mobile username and "服务器中继正常" when synced recently', async () => {
    const now = Math.floor(Date.now() / 1000)
    mockApiFetch.mockResolvedValue(jsonRes({ paired: true, mobileUsername: '李雷', lastRelaySyncAt: now - 5 }))
    const wrapper = mount(MobilePairingQrCard)
    await flushPromises()
    expect(wrapper.text()).toContain('已连接：李雷 的手机')
    expect(wrapper.text()).toContain('服务器中继正常')
    expect(wrapper.find('.mobile-pairing__status--connected').exists()).toBe(true)
  })

  it('shows stale-sync warning when last sync is old', async () => {
    const now = Math.floor(Date.now() / 1000)
    mockApiFetch.mockResolvedValue(jsonRes({ paired: true, mobileUsername: '王五', lastRelaySyncAt: now - 20 * 60 }))
    const wrapper = mount(MobilePairingQrCard)
    await flushPromises()
    expect(wrapper.text()).toContain('中继暂时不通')
    expect(wrapper.find('.mobile-pairing__status--stale').exists()).toBe(true)
  })

  it('falls back to pending state when the status request fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('network error'))
    const wrapper = mount(MobilePairingQrCard)
    await flushPromises()
    expect(wrapper.text()).toContain('尚未绑定手机')
  })
})
