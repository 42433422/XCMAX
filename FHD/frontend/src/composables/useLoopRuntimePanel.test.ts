import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent } from 'vue'

const statusMock = vi.fn()
vi.mock('@/api/xcmaxMarketProxy', () => ({
  default: {
    selfMaintenanceRuntimeStatus: (...args: unknown[]) => statusMock(...args),
  },
}))

import { asArray, asNumber, asRecord, asString, firstText, useLoopRuntimePanel } from './useLoopRuntimePanel'

function makeHost(getLimit: () => number) {
  return defineComponent({
    setup() {
      return useLoopRuntimePanel(getLimit)
    },
    template: '<div />',
  })
}

describe('pure helpers', () => {
  it('asRecord 只收口普通对象', () => {
    expect(asRecord(null)).toEqual({})
    expect(asRecord([])).toEqual({})
    expect(asRecord({ a: 1 })).toEqual({ a: 1 })
  })

  it('asArray 只收口数组', () => {
    expect(asArray('x')).toEqual([])
    expect(asArray([1, 2])).toEqual([1, 2])
    expect(asArray(undefined)).toEqual([])
  })

  it('asString 去空白并转字符串', () => {
    expect(asString('  a  ')).toBe('a')
    expect(asString(0)).toBe('0')
    expect(asString(null)).toBe('')
  })

  it('asNumber 非法数字回退 fallback', () => {
    expect(asNumber('3.5')).toBe(3.5)
    expect(asNumber('abc')).toBe(0)
    expect(asNumber('abc', 7)).toBe(7)
  })

  it('firstText 取第一个非空文本', () => {
    expect(firstText('', 'b', 'c')).toBe('b')
    expect(firstText(null, undefined, 'z')).toBe('z')
    expect(firstText('', undefined, null)).toBe('')
  })
})

const valid = () => ({
  ok: true,
  schema_version: 'self_maintenance_runtime.v1',
  generated_at: new Date().toISOString(),
  evidence: { open_run_ids: [] },
  run_timelines: [],
})
const wrappers: ReturnType<typeof mount>[] = []
function setup() {
  const wrapper = mount(makeHost(() => 40))
  wrappers.push(wrapper)
  return wrapper.vm as unknown as { raw: unknown; error: string; connection: string; refresh: () => Promise<boolean> }
}

beforeEach(() => {
  vi.useFakeTimers()
  statusMock.mockReset().mockResolvedValue(valid())
})
afterEach(() => {
  wrappers.splice(0).forEach((w) => w.unmount())
  vi.useRealTimers()
})

describe('maintenance polling', () => {
  it('keeps errors visible during retry and recovers without losing evidence', async () => {
    const state = setup()
    await flushPromises()
    const snapshot = state.raw
    expect(state.connection).toBe('connected')
    statusMock.mockRejectedValueOnce(new Error('offline'))
    await state.refresh()
    expect(state.raw).toEqual(snapshot)
    expect(state.connection).toBe('error')
    let done!: (value: unknown) => void
    statusMock.mockReturnValueOnce(
      new Promise((resolve) => {
        done = resolve
      }),
    )
    const refresh = state.refresh()
    expect(state.error).toBe('offline')
    done(valid())
    await refresh
    expect(state.connection).toBe('connected')
  })
  it('does not overlap reads and aborts on disposal', async () => {
    statusMock.mockReturnValue(new Promise(() => {}))
    const state = setup()
    expect(state.connection).toBe('loading')
    await state.refresh()
    await vi.advanceTimersByTimeAsync(90000)
    expect(statusMock).toHaveBeenCalledTimes(1)
    const signal = statusMock.mock.calls[0][1]
    wrappers[0].unmount()
    expect(signal.aborted).toBe(true)
  })
  it('backs off on failures', async () => {
    statusMock.mockRejectedValue(new Error('offline'))
    setup()
    await flushPromises()
    await vi.advanceTimersByTimeAsync(30000)
    expect(statusMock).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(30000)
    expect(statusMock).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(30000)
    expect(statusMock).toHaveBeenCalledTimes(3)
  })
  it.each([{}, { ok: false }, { ...valid(), run_timelines: undefined }])('rejects malformed data without claiming idle', async (data) => {
    statusMock.mockResolvedValue(data)
    const state = setup()
    await flushPromises()
    expect(state.raw).toBeNull()
    expect(state.connection).toBe('error')
  })
  it('ages snapshots independently of network reads', async () => {
    const state = setup()
    await flushPromises()
    statusMock.mockReturnValue(new Promise(() => {}))
    await vi.advanceTimersByTimeAsync(135000)
    expect(state.connection).toBe('stale')
  })
})
