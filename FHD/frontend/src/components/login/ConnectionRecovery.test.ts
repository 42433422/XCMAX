import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import api from '@/api'
import ConnectionRecovery from './ConnectionRecovery.vue'

vi.mock('@/api', () => ({ default: { get: vi.fn() } }))
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.clearAllMocks() })

describe('connection recovery', () => {
  it('checks on request and copies only safe diagnostic categories even when the transport error contains secrets', async () => {
    const copy = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { onLine: true, clipboard: { writeText: copy } })
    vi.mocked(api.get).mockRejectedValue({ status: 503, message: 'https://user:secret@example.com?token=private email=private@example.com' })
    const wrapper = mount(ConnectionRecovery, { props: { code: 'AUTH_SEND_CODE' } })
    expect(api.get).not.toHaveBeenCalled()
    await wrapper.findAll('button')[0].trigger('click')
    await flushPromises()
    expect(api.get).toHaveBeenCalledWith('/api/health', { lite: true }, { timeoutMs: 5000 })
    expect(wrapper.text()).toContain('退出并重新打开应用')
    await wrapper.findAll('button')[1].trigger('click')
    expect(copy).toHaveBeenCalledExactlyOnceWith(expect.stringContaining('AUTH_SEND_CODE'))
    expect(copy.mock.calls[0][0]).not.toMatch(/secret|private|example\.com|token=/)
    expect(wrapper.text()).toContain('已复制')
    wrapper.unmount()
  })
  it('does not equate successful health with successful authentication and offers manual copy after clipboard failure', async () => {
    vi.mocked(api.get).mockResolvedValue({ ok: true })
    vi.stubGlobal('navigator', { onLine: true, clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } })
    const wrapper = mount(ConnectionRecovery)
    await wrapper.findAll('button')[0].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('若原操作仍失败')
    await wrapper.findAll('button')[1].trigger('click')
    expect(wrapper.text()).toContain('手动复制')
    expect(wrapper.get('details pre').text()).toContain('LOGIN_CONNECTION')
    wrapper.unmount()
  })
})
