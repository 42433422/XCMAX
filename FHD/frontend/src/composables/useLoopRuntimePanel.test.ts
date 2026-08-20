import { describe, it, expect, vi, beforeEach } from 'vitest'
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

describe('useLoopRuntimePanel', () => {
  beforeEach(() => {
    statusMock.mockReset()
    statusMock.mockResolvedValue({})
  })

  it('挂载时调用接口并写入 raw，limit 来自 getLimit', async () => {
    statusMock.mockResolvedValue({ evidence: { open_run_ids: ['r1'] } })
    const wrapper = mount(makeHost(() => 40))
    await flushPromises()
    expect(statusMock).toHaveBeenCalledWith(40)
    expect((wrapper.vm as { raw: unknown }).raw).toEqual({ evidence: { open_run_ids: ['r1'] } })
    expect((wrapper.vm as { loading: boolean }).loading).toBe(false)
  })

  it('接口失败时写入 error', async () => {
    statusMock.mockRejectedValue(new Error('网络异常'))
    const wrapper = mount(makeHost(() => 80))
    await flushPromises()
    expect((wrapper.vm as { error: string }).error).toBe('网络异常')
  })

  it('手动 refresh 携带 getLimit 返回值', async () => {
    statusMock.mockResolvedValue({})
    const wrapper = mount(makeHost(() => 80))
    await flushPromises()
    expect(statusMock).toHaveBeenNthCalledWith(1, 80)
    await (wrapper.vm as { refresh: () => Promise<void> }).refresh()
    expect(statusMock).toHaveBeenNthCalledWith(2, 80)
  })

  it('卸载时不抛错（清理定时器）', async () => {
    statusMock.mockResolvedValue({})
    const wrapper = mount(makeHost(() => 80))
    await flushPromises()
    expect(() => wrapper.unmount()).not.toThrow()
  })
})
