import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { useOpenIMGroup } from '../useOpenIMGroup'
import { apiFetch } from '@/utils/apiBase'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
vi.mock('@/utils/apiBase', () => ({ apiFetch: vi.fn() }))
const wasm = vi.spyOn(WebAssembly, 'compile').mockResolvedValue({} as WebAssembly.Module)
afterEach(() => { vi.mocked(apiFetch).mockReset() })
const session = { enabled: true, userID: 'owner', token: 'synthetic', platformID: 5, apiAddr: '', wsAddr: '', groupID: 'remote', senders: {} }
function setup() {
  let transport!: ReturnType<typeof useOpenIMGroup>
  const wrapper = mount(defineComponent({ setup() { transport = useOpenIMGroup(vi.fn()); return () => null } }))
  return { transport, wrapper }
}
it('removes failed SDK scripts and permits retry while leaving host synchronization available', async () => {
  vi.mocked(apiFetch).mockResolvedValue({ ok: true, json: async () => session } as Response)
  const { transport, wrapper } = setup()
  try {
    for (let attempt = 0; attempt < 2; attempt++) {
      const pending = transport.start('local')
      await flushPromises()
      const script = document.querySelector('script[src$="openim/wasm_exec.js"]')!
      expect(script).not.toBeNull()
      script.dispatchEvent(new Event('error'))
      expect(await pending).toBe(false)
      expect(document.contains(script)).toBe(false)
      expect(transport.active.value).toBe(false)
      expect(transport.error.value).toContain('主机消息同步')
    }
  } finally { wrapper.unmount() }
})
it('does not load SDK when transport is disabled', async () => {
  vi.mocked(apiFetch).mockResolvedValue({ ok: true, json: async () => ({ enabled: false }) } as Response)
  const { transport, wrapper } = setup()
  try { expect(await transport.start('local')).toBe(false); expect(transport.active.value).toBe(false) }
  finally { wrapper.unmount() }
})
it('retires a late transport response after switching account', async () => {
  let resolve!: (value: Response) => void
  vi.mocked(apiFetch).mockImplementationOnce(() => new Promise(r => { resolve = r }))
  const { transport, wrapper } = setup()
  try {
    const pending = transport.start('local')
    await flushPromises()
    productReadAccountEpoch.value++
    resolve({ ok: true, json: async () => session } as Response)
    expect(await pending).toBe(true)
    expect(transport.active.value).toBe(false)
    expect(transport.error.value).toContain('账号已切换')
  } finally { wrapper.unmount() }
})
it('does not request transport after unmounting during queued logout', async () => {
  const { transport, wrapper } = setup()
  const pending = transport.start('local')
  wrapper.unmount()
  expect(await pending).toBe(true)
  expect(apiFetch).not.toHaveBeenCalled()
  wasm.mockRestore()
})
