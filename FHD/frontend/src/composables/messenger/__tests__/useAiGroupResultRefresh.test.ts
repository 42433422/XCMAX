import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { useAiGroupResultRefresh } from '../useAiGroupResultRefresh'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
const fetchMessages = vi.hoisted(() => vi.fn())
vi.mock('@/api/aiGroups', () => ({ fetchAiGroupMessages: fetchMessages }))
let wrapper: ReturnType<typeof mount>
beforeEach(() => { vi.useFakeTimers(); fetchMessages.mockReset(); vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible') })
afterEach(() => { wrapper?.unmount(); vi.useRealTimers(); vi.restoreAllMocks() })
function setup() {
  const group = ref('one'), enabled = ref(true), receive = vi.fn()
  let error: ReturnType<typeof useAiGroupResultRefresh>
  wrapper = mount(defineComponent({ setup() {
    error = useAiGroupResultRefresh(() => group.value, () => enabled.value, receive)
    return () => null
  } }))
  return { group, enabled, receive, error: () => error.value }
}
const row = { id: 'receipt', group_id: 'one', body: 'synthetic result' }
describe('host receipt refresh with a live SDK connection', () => {
  it('periodically pulls existing host receipts, filters foreign groups and surfaces recovery', async () => {
    fetchMessages.mockRejectedValueOnce(new Error('offline')).mockResolvedValue([row, { ...row, group_id: 'other' }])
    const state = setup()
    await vi.advanceTimersByTimeAsync(5000)
    expect(state.error()).toContain('任务回执同步失败')
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetchMessages).toHaveBeenCalledTimes(2)
    expect(fetchMessages).toHaveBeenLastCalledWith('one', 'admin', expect.any(AbortSignal))
    expect(state.receive).toHaveBeenCalledWith([row])
    expect(state.error()).toBe('')
  })
  it('does not overlap slow requests and ignores their completion after group replacement', async () => {
    let resolve!: (rows: typeof row[]) => void
    fetchMessages.mockImplementationOnce(() => new Promise(r => { resolve = r })).mockResolvedValue([])
    const state = setup()
    await vi.advanceTimersByTimeAsync(15000)
    expect(fetchMessages).toHaveBeenCalledTimes(1)
    const signal = fetchMessages.mock.calls[0][2] as AbortSignal
    state.group.value = 'two'
    expect(signal.aborted).toBe(true)
    resolve([row]); await flushPromises()
    expect(state.receive).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetchMessages).toHaveBeenLastCalledWith('two', 'admin', expect.any(AbortSignal))
  })
  for (const reason of ['disconnect', 'account', 'unmount']) {
    it(`aborts and rejects stale receipts after ${reason}`, async () => {
      let resolve!: (rows: typeof row[]) => void
      fetchMessages.mockImplementation(() => new Promise(r => { resolve = r }))
      const state = setup()
      await vi.advanceTimersByTimeAsync(5000)
      const signal = fetchMessages.mock.calls[0][2] as AbortSignal
      if (reason === 'disconnect') state.enabled.value = false
      else if (reason === 'account') productReadAccountEpoch.value++
      else wrapper.unmount()
      expect(signal.aborted).toBe(true)
      resolve([row]); await flushPromises()
      document.dispatchEvent(new Event('visibilitychange'))
      await vi.advanceTimersByTimeAsync(15000)
      expect(state.receive).not.toHaveBeenCalled()
      expect(fetchMessages).toHaveBeenCalledTimes(1)
    })
  }
})
