import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import { useCodexStreamEngine } from '../useCodexStreamEngine'

afterEach(() => vi.useRealTimers())
const engine = () => useCodexStreamEngine({
  codexMessages: ref([]), codexScrollEl: ref(null), activeSystemEntry: ref(null), fetchActiveSuperMessages: async () => [],
})

describe('completed super-employee replies', () => {
  it('does not pull a reader away from earlier messages when a completed result appears', async () => {
    const el = { scrollTop: 120, scrollHeight: 1000, clientHeight: 200 } as HTMLElement
    const stream = useCodexStreamEngine({ codexMessages: ref([]), codexScrollEl: ref(el), activeSystemEntry: ref(null), fetchActiveSuperMessages: async () => [] })
    stream.startCodexTypewriter({ body: '结果'.repeat(10000), active: false })
    await nextTick()
    expect(el.scrollTop).toBe(120)
    el.scrollTop = 800
    stream.startCodexTypewriter({ body: '完整结果'.repeat(10000), active: false })
    await nextTick()
    expect(el.scrollTop).toBe(1000)
  })
  it.each([1000, 5000, 10000, 20000])('makes all %s characters readable without an animation tick', (length) => {
    vi.useFakeTimers()
    const stream = engine()
    const body = '测'.repeat(length)
    stream.startCodexTypewriter({ body, messageId: 'result', active: false, reset: true })
    expect(stream.codexStreamBody.value).toBe(body)
    expect(stream.codexStreamActive.value).toBe(false)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('replaces live progress and retires its timer when the matching result arrives', async () => {
    vi.useFakeTimers()
    const stream = engine()
    stream.startCodexTypewriter({ body: '正在执行'.repeat(100), requestId: 'r1', active: true })
    await vi.advanceTimersByTimeAsync(34)
    expect(vi.getTimerCount()).toBe(1)
    const body = '完整结果'.repeat(5000)
    expect(stream.syncCodexStreamFromMessages([
      { id: 'result', role: 'assistant', kind: 'codex_result', body, created_at: 'now', dispatch_request_id: 'r1' },
    ], 'r1')).toBe(false)
    expect(stream.codexStreamBody.value).toBe(body)
    expect(stream.codexStreamMessageId.value).toBe('result')
    expect(stream.codexStreamActive.value).toBe(false)
    expect(vi.getTimerCount()).toBe(0)
  })
})
