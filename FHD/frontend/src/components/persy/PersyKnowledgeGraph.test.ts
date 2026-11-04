import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PersyKnowledgeGraph from './PersyKnowledgeGraph.vue'
import type { KnowledgeGraphResponse } from '@/api/knowledgeBase'

const mocks = vi.hoisted(() => {
  const chart = {
    setOption: vi.fn(),
    resize: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    dispose: vi.fn(),
  }
  return {
    chart,
    init: vi.fn(() => chart),
    use: vi.fn(),
  }
})

vi.mock('echarts/core', () => ({
  init: mocks.init,
  use: mocks.use,
}))
vi.mock('echarts/charts', () => ({ GraphChart: {} }))
vi.mock('echarts/components', () => ({ TooltipComponent: {} }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

let resizeObserved: () => void
class ResizeObserverStub {
  constructor(callback: () => void) { resizeObserved = callback }
  observe = vi.fn()
  disconnect = vi.fn()
}

const graph: KnowledgeGraphResponse = {
  success: true,
  dataset_id: 'persy-knowledge',
  nodes: [
    { id: 'persy:persy-knowledge', label: 'Persy', type: 'core', size: 72 },
    {
      id: 'document:policy',
      label: '续约制度.md',
      type: 'source',
      document_id: 'policy',
      size: 38,
    },
    {
      id: 'knowledge:approval',
      label: '高价值续约需要财务审批',
      type: 'knowledge',
      document_id: 'policy',
      chunk_index: 0,
      source: '续约制度.md',
    },
  ],
  edges: [
    {
      id: 'edge:document:knowledge',
      source: 'document:policy',
      target: 'knowledge:approval',
      type: 'contains',
    },
  ],
}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', ResizeObserverStub)
  vi.clearAllMocks()
})

describe('PersyKnowledgeGraph', () => {

  it('renders real graph nodes and recall edges', async () => {
    const wrapper = mount(PersyKnowledgeGraph, {
      props: {
        graph,
        recall: {
          query: '谁审批续约？',
          chunks: [
            {
              text: '高价值续约需要财务审批。',
              source: '续约制度.md',
              chunk_index: 0,
              metadata: { document_id: 'policy' },
            },
          ],
        },
      },
    })
    await flushPromises()

    expect(mocks.init).toHaveBeenCalledTimes(1)
    const option = mocks.chart.setOption.mock.calls.at(-1)?.[0]
    const escaped = option.tooltip.formatter({ dataType: 'edge', data: { value: `<&"'> <&"'>` } })
    expect(escaped).toBe('&lt;&amp;&quot;&#039;&gt; &lt;&amp;&quot;&#039;&gt;')
    const series = option.series[0]
    expect(series.type).toBe('graph')
    expect(series.data.map((node: { id: string }) => node.id)).toEqual(
      expect.arrayContaining(['persy:persy-knowledge', 'document:policy', 'knowledge:approval', 'recall:current-query']),
    )
    expect(series.labelLayout).toEqual({ hideOverlap: true })
    expect(series.links.some((edge: { type?: string }) => edge.lineStyle.color === '#d39a29')).toBe(true)

    wrapper.unmount()
    expect(mocks.chart.dispose).toHaveBeenCalledTimes(1)
  })

  it('emits real onboarding actions from an empty graph', async () => {
    const wrapper = mount(PersyKnowledgeGraph, {
      props: {
        graph: {
          success: true,
          dataset_id: 'persy-knowledge',
          nodes: [{ id: 'persy:persy-knowledge', label: 'Persy', type: 'core' }],
          edges: [],
        },
      },
    })
    await flushPromises()

    const option = mocks.chart.setOption.mock.calls.at(-1)?.[0]
    const uploadNode = option.series[0].data.find((node: { id: string }) => node.id === 'onboarding:upload')
    const clickHandler = mocks.chart.on.mock.calls.find((call) => call[0] === 'click')?.[1]
    clickHandler({ dataType: 'node', data: uploadNode })

    expect(wrapper.emitted('onboardingAction')).toEqual([['upload']])
    expect(wrapper.text()).toContain('当前没有知识内容')
    wrapper.unmount()
  })

  it('emits the selected knowledge node for the detail panel', async () => {
    const wrapper = mount(PersyKnowledgeGraph, { props: { graph } })
    await flushPromises()

    const option = mocks.chart.setOption.mock.calls.at(-1)?.[0]
    const knowledgeNode = option.series[0].data.find((node: { id: string }) => node.id === 'knowledge:approval')
    const clickHandler = mocks.chart.on.mock.calls.find((call) => call[0] === 'click')?.[1]
    clickHandler({ dataType: 'node', data: knowledgeNode })

    expect(wrapper.emitted('selectNode')).toEqual([
      [expect.objectContaining({ id: 'knowledge:approval', type: 'knowledge', metadata: {} })],
    ])
    wrapper.unmount()
  })

  it('links memory recall evidence and marks pending memory as unconfirmed', async () => {
    const memoryGraph: KnowledgeGraphResponse = {
      ...graph,
      nodes: [
        ...graph.nodes,
        {
          id: 'memory:mem-1',
          label: '用户的偏好是下午沟通',
          type: 'memory',
          metadata: { memory_id: 'mem-1', status: 'pending' },
        },
      ],
    }
    const wrapper = mount(PersyKnowledgeGraph, {
      props: {
        graph: memoryGraph,
        recall: {
          query: '我什么时候沟通？',
          chunks: [
            {
              text: '用户的偏好是下午沟通',
              source: '对话记忆',
              metadata: { memory_id: 'mem-1' },
            },
          ],
        },
      },
    })
    await flushPromises()

    const option = mocks.chart.setOption.mock.calls.at(-1)?.[0]
    const memoryNode = option.series[0].data.find((node: { id: string }) => node.id === 'memory:mem-1')
    const recallLink = option.series[0].links.find(
      (edge: { source: string; target: string }) => edge.source === 'recall:current-query' && edge.target === 'memory:mem-1',
    )
    expect(memoryNode.itemStyle.borderType).toBe('dashed')
    expect(memoryNode.itemStyle.borderColor).toBe('#f7c84a')
    expect(memoryNode.label.position).toBe('top')
    expect(recallLink).toBeTruthy()
    wrapper.unmount()
  })
})


afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
it('caps dense graphs by strength, keeps sticky nodes, escapes tooltips and refreshes selected nodes', async () => {
  vi.useFakeTimers()
  const nodes = Array.from({ length: 70 }, (_, index) => ({ id: `k${index}`, type: 'knowledge',
    label: `Knowledge ${index} with a very long name`, strength: index / 100, chunk_index: index, source: 'guide.md' }))
  const special = [{ id: 'pending', type: 'memory', label: '待确认记忆', metadata: { status: 'pending' } },
    { id: 'topic', type: 'topic', label: '主题' }, { id: 'custom', type: 'custom', label: '<unsafe>', summary: '<script>' }]
  const wrapper = mount(PersyKnowledgeGraph, { props: { graph: { success: true, dataset_id: 'large', nodes: [...nodes, ...special],
    edges: [{ id: 'valid', source: 'k69', target: 'topic', type: 'related', weight: 0.9 },
      { id: 'missing', source: 'k0', target: 'missing', type: 'related' }] },
    selectedNodeId: 'k69', recall: { query: 'An unmatched question with more than twenty eight letters', chunks: [{ source: 'guide.md+rerank', chunk_index: 68 }] } } })
  await flushPromises()
  const option = () => mocks.chart.setOption.mock.calls.at(-1)![0]
  expect(option().series[0].data).toHaveLength(56)
  expect(option().animation).toBe(false)
  expect(option().series[0].force.layoutAnimation).toBe(false)
  expect(option().series[0].data.find((x: any) => x.id === 'k69').itemStyle.borderWidth).toBe(3)
  expect(option().series[0].data.find((x: any) => x.id === 'pending').itemStyle.opacity).toBe(0.72)
  expect(option().series[0].links.map((x: any) => x.id)).not.toContain('missing')
  expect(option().series[0].links.some((x: any) => x.target === 'k68' && x.source === 'recall:current-query')).toBe(true)
  expect(option().tooltip.formatter({ data: { rawNode: special[2] } })).toContain('&lt;script&gt;')
  expect(option().tooltip.formatter({ data: { rawNode: nodes[69] } })).not.toContain('<br/><br/>')
  expect(option().tooltip.formatter({ dataType: 'edge' })).toBe('关系')
  expect(option().tooltip.formatter({})).toBe('')
  const click = mocks.chart.on.mock.calls.find(x => x[0] === 'click')![1]
  for (const payload of [{ dataType: 'edge' }, { dataType: 'node' }, { dataType: 'node', data: { rawNode: { type: 'onboarding' } } }]) click(payload)
  expect(wrapper.emitted('selectNode')).toBeUndefined()
  resizeObserved(); window.dispatchEvent(new Event('resize'))
  expect(mocks.chart.resize).toHaveBeenCalledTimes(2)
  wrapper.vm.resetView(); expect(mocks.chart.resize).toHaveBeenCalledTimes(3)
  await wrapper.setProps({ graph: null, selectedNodeId: '', loading: true, recall: null })
  await vi.advanceTimersByTimeAsync(16)
  expect(wrapper.get('[role="status"]').text()).toContain('正在整理知识关系')
  expect(option().series[0].data).toHaveLength(1)
  await wrapper.setProps({ loading: false, recall: { query: 'No match', chunks: [] } })
  await vi.advanceTimersByTimeAsync(16)
  expect(option().series[0].links.some((x: any) => x.source === 'recall:current-query' && x.target === 'persy:persy-knowledge')).toBe(true)
  for (const node of option().series[0].data.filter((x: any) => x.id.startsWith('onboarding:'))) click({ dataType: 'node', data: node })
  expect(wrapper.emitted('onboardingAction')).toEqual([['upload'], ['paste'], ['chat']])
  await wrapper.setProps({ loading: true }); wrapper.unmount()
  await vi.advanceTimersByTimeAsync(16)
  expect(mocks.chart.off).toHaveBeenCalledWith('click', click)
})
