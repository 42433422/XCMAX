import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { knowledgeBaseApi, type PersyMemoryQueryResponse, type PersyMemoryRecord } from '@/api/knowledgeBase'
import PersyMemoryTemporalReview from './PersyMemoryTemporalReview.vue'

vi.mock('@/api/knowledgeBase', () => ({ knowledgeBaseApi: { queryMemories: vi.fn() } }))

const queryMemories = vi.mocked(knowledgeBaseApi.queryMemories)
const memory: PersyMemoryRecord = {
  memory_id: 'memory-a', memory_type: 'entity', statement: '客户甲由小李负责',
  status: 'active', scope: 'tenant', revision: 3,
}
const response = (extra: Partial<PersyMemoryQueryResponse> = {}): PersyMemoryQueryResponse => ({
  success: true, memories: [], chunks: [], ...extra,
})
function deferred() {
  let resolve!: (value: PersyMemoryQueryResponse) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<PersyMemoryQueryResponse>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
let wrapper: VueWrapper
async function openReview() {
  wrapper = mount(PersyMemoryTemporalReview, { props: { datasetId: 'dataset-a', refreshKey: [] } })
  const details = wrapper.get('details')
  ;(details.element as HTMLDetailsElement).open = true
  await details.trigger('toggle')
  return wrapper
}
async function submit(query = '客户甲') {
  await wrapper.get('input[type="text"]').setValue(query)
  await wrapper.get('form').trigger('submit')
}

beforeEach(() => { queryMemories.mockReset() })
afterEach(() => { if (wrapper?.exists()) wrapper.unmount() })

describe('PersyMemoryTemporalReview', () => {
  it('submits a read-only temporal query and distinguishes history, incomplete coverage and relation conflicts', async () => {
    const pending = deferred()
    queryMemories.mockReturnValueOnce(pending.promise)
    await openReview()
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
    await wrapper.get('form').trigger('submit')
    expect(queryMemories).not.toHaveBeenCalled()
    await wrapper.get('select').setValue('3')
    const inputs = wrapper.findAll('input')
    await inputs[1].setValue(' 2026-11-24T08:00:00+08:00 ')
    await inputs[2].setValue(' 2026-11-23T08:00:00+08:00 ')
    await submit(' 客户甲 ')
    await wrapper.get('form').trigger('submit')
    expect(queryMemories).toHaveBeenCalledExactlyOnceWith({
      datasetId: 'dataset-a', query: '客户甲', maxHops: 3, reinforce: false,
      asOf: '2026-11-24T08:00:00+08:00', effectiveAt: '2026-11-23T08:00:00+08:00',
    })
    expect(wrapper.get('button').text()).toBe('查询中')
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
    pending.resolve(response({
      historical_review_only: true, coverage_complete: false, temporal_unavailable_count: 2,
      revalidation_dropped: 1, relation_conflict_count: 1,
      relation_conflicts: [{ predicate: '负责人', memory_ids: ['conflict-a', 'conflict-b'] }],
      memories: [{ ...memory, recorded_from: '2026-11-20', recorded_until: '2026-11-22', relation_path: [
        { statement: '原记录关联', identity_basis: 'recorded_id', revision: 2 },
        { statement: '同名候选关联', identity_basis: 'name', revision: 1 },
      ] }, { ...memory, memory_id: 'memory-b', revision: undefined, recorded_from: '2026-11-23' }],
    }))
    await flushPromises()
    expect(wrapper.text()).toContain('仅供审核，不进入 AI 执行上下文')
    expect(wrapper.text()).toContain('不能将未返回的内容视为不存在')
    expect(wrapper.text()).toContain('时间信息不足：2；并发修订过滤：1')
    expect(wrapper.text()).toContain('发现 1 组单值关系冲突')
    expect(wrapper.text()).toContain('conflict-a')
    expect(wrapper.text()).toContain('conflict-b')
    expect(wrapper.text()).toContain('修订 3 · memory-a')
    expect(wrapper.text()).toContain('修订 未知 · memory-b')
    expect(wrapper.text()).toContain('2026-11-20 至 2026-11-22')
    expect(wrapper.text()).toContain('2026-11-23 至 当前')
    expect(wrapper.text()).toContain('记录ID关联；修订 2')
    expect(wrapper.text()).toContain('名称候选关联；修订 1')
    expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
  })

  it('omits optional times and renders an empty, incomplete result without inventing missing counts', async () => {
    queryMemories.mockResolvedValue(response({ coverage_complete: false }))
    await openReview()
    await submit()
    await flushPromises()
    expect(queryMemories).toHaveBeenCalledExactlyOnceWith({
      datasetId: 'dataset-a', query: '客户甲', maxHops: 2, reinforce: false,
    })
    expect(wrapper.text()).toContain('没有符合条件的可用记录')
    expect(wrapper.text()).toContain('时间信息不足：0；并发修订过滤：0')
    expect(wrapper.text()).not.toContain('仅供审核，不进入 AI 执行上下文')
    expect(wrapper.findAll('ol')).toHaveLength(0)
  })

  it.each([
    ['reported failure', () => Promise.resolve(response({ success: false, message: '无权查询' })), '无权查询'],
    ['missing failure detail', () => Promise.resolve(response({ success: false })), '查询失败'],
    ['transport error', () => Promise.reject(new Error('连接中断')), '连接中断'],
    ['non-error rejection', () => Promise.reject('unavailable'), '查询失败'],
  ] as const)('shows %s and clears it when the user retries successfully', async (_name, failure, message) => {
    queryMemories.mockImplementationOnce(failure).mockResolvedValue(response())
    await openReview()
    await submit()
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe(message)
    expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
    await submit()
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('没有符合条件的可用记录')
  })

  it.each(['dataset', 'memory revision', 'closed panel'])('discards late results after %s changes', async (change) => {
    const old = deferred()
    queryMemories.mockReturnValueOnce(old.promise).mockResolvedValue(response({ memories: [memory] }))
    await openReview()
    await submit()
    if (change === 'dataset') await wrapper.setProps({ datasetId: 'dataset-b' })
    else if (change === 'memory revision') await wrapper.setProps({ refreshKey: [memory] })
    else {
      const details = wrapper.get('details')
      ;(details.element as HTMLDetailsElement).open = false
      await details.trigger('toggle')
    }
    old.resolve(response({ memories: [{ ...memory, statement: '过期查询结果' }] }))
    await flushPromises()
    expect(wrapper.find('[aria-live="polite"]').exists()).toBe(false)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('button').text()).toBe('查询')
    const details = wrapper.get('details')
    ;(details.element as HTMLDetailsElement).open = true
    await details.trigger('toggle')
    await submit()
    await flushPromises()
    expect(wrapper.text()).toContain(memory.statement)
    expect(wrapper.text()).not.toContain('过期查询结果')
    expect(queryMemories.mock.lastCall?.[0].datasetId).toBe(change === 'dataset' ? 'dataset-b' : 'dataset-a')
  })

  it('keeps the replacement query loading when an invalidated request fails', async () => {
    const old = deferred(), current = deferred()
    queryMemories.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    await openReview()
    await submit()
    await wrapper.setProps({ datasetId: 'dataset-b' })
    await submit()
    old.reject(new Error('过期错误'))
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('button').text()).toBe('查询中')
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
    current.resolve(response({ memories: [memory] }))
    await flushPromises()
    expect(wrapper.text()).toContain(memory.statement)
    expect(wrapper.get('button').text()).toBe('查询')
  })

  it('settles an in-flight request safely after the panel unmounts', async () => {
    const pending = deferred()
    queryMemories.mockReturnValueOnce(pending.promise)
    await openReview()
    await submit()
    expect(queryMemories).toHaveBeenCalledTimes(1)
    wrapper.unmount()
    pending.reject(new Error('已离开此页面'))
    await flushPromises()
    expect(wrapper.exists()).toBe(false)
    expect(queryMemories).toHaveBeenCalledTimes(1)
  })
})
