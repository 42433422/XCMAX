import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
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

class ResizeObserverStub {
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

describe('PersyKnowledgeGraph', () => {
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    mocks.init.mockClear()
    mocks.chart.setOption.mockClear()
    mocks.chart.resize.mockClear()
    mocks.chart.on.mockClear()
    mocks.chart.off.mockClear()
    mocks.chart.dispose.mockClear()
  })

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
    const series = option.series[0]
    expect(series.type).toBe('graph')
    expect(series.data.map((node: { id: string }) => node.id)).toEqual(
      expect.arrayContaining([
        'persy:persy-knowledge',
        'document:policy',
        'knowledge:approval',
        'recall:current-query',
      ]),
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
    const uploadNode = option.series[0].data.find(
      (node: { id: string }) => node.id === 'onboarding:upload',
    )
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
    const knowledgeNode = option.series[0].data.find(
      (node: { id: string }) => node.id === 'knowledge:approval',
    )
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
    const memoryNode = option.series[0].data.find(
      (node: { id: string }) => node.id === 'memory:mem-1',
    )
    const recallLink = option.series[0].links.find(
      (edge: { source: string; target: string }) =>
        edge.source === 'recall:current-query' && edge.target === 'memory:mem-1',
    )
    expect(memoryNode.itemStyle.borderType).toBe('dashed')
    expect(memoryNode.itemStyle.borderColor).toBe('#f7c84a')
    expect(memoryNode.label.position).toBe('top')
    expect(recallLink).toBeTruthy()
    wrapper.unmount()
  })

  it('renders ERP ontology constraints as first-class semantic nodes', async () => {
    const erpGraph: KnowledgeGraphResponse = {
      ...graph,
      nodes: [
        ...graph.nodes,
        {
          id: 'erp:ontology',
          label: 'ERP 领域本体',
          type: 'erp_ontology',
          metadata: { ontology_version: 'erp_domain_ontology_v1' },
        },
        {
          id: 'erp-rule:accounting.double_entry_balance',
          label: '借贷必平衡',
          type: 'erp_constraint',
          summary: '每张已过账凭证必须满足借方金额合计等于贷方金额合计。',
          metadata: {
            erp_domain_label: '财务会计',
            symbolic_expression: "sum(debit) == sum(credit)",
          },
        },
      ],
      edges: [
        ...graph.edges,
        {
          id: 'edge:persy:erp',
          source: 'persy:persy-knowledge',
          target: 'erp:ontology',
          type: 'erp_ontology',
          label: '领域语义',
        },
      ],
    }

    const wrapper = mount(PersyKnowledgeGraph, { props: { graph: erpGraph } })
    await flushPromises()

    const option = mocks.chart.setOption.mock.calls.at(-1)?.[0]
    const erpConstraint = option.series[0].data.find(
      (node: { id: string }) => node.id === 'erp-rule:accounting.double_entry_balance',
    )
    const erpLink = option.series[0].links.find(
      (edge: { source: string; target: string }) =>
        edge.source === 'persy:persy-knowledge' && edge.target === 'erp:ontology',
    )
    expect(erpConstraint.label.show).toBe(true)
    expect(erpConstraint.label.position).toBe('top')
    expect(erpLink.lineStyle.color).toBe('#8a6b36')
    wrapper.unmount()
  })
})
