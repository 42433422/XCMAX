import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

// Mock @vue-flow/core and sub-modules
vi.mock('@vue-flow/core', () => ({
  VueFlow: {
    name: 'VueFlow',
    props: ['id', 'nodes', 'edges', 'nodesConnectable', 'elementsSelectable', 'fitViewOnInit'],
    template: '<div class="vue-flow-mock"><slot /><slot name="node-group" /><slot name="node-default" /></div>',
  },
  useVueFlow: () => ({
    fitView: vi.fn(),
  }),
}))
vi.mock('@vue-flow/background', () => ({
  Background: { name: 'Background', template: '<div class="bg-mock" />' },
}))
vi.mock('@vue-flow/controls', () => ({
  Controls: { name: 'Controls', template: '<div class="controls-mock" />' },
}))
vi.mock('@vue-flow/minimap', () => ({
  MiniMap: { name: 'MiniMap', template: '<div class="minimap-mock" />' },
}))
vi.mock('@/composables/useAutoLayout', () => ({
  computeGridLayout: (ids: string[], opts: Record<string, number>) => {
    const positions = new Map<string, { x: number; y: number }>()
    const cols = opts.cols || 2
    let x = 0
    let y = 0
    for (const id of ids) {
      positions.set(id, { x, y })
      x += opts.cellWidth + (opts.gapX || 0)
      if ((positions.size) % cols === 0) {
        x = 0
        y += opts.cellHeight + (opts.gapY || 0)
      }
    }
    const width = Math.max(240, cols * (opts.cellWidth + opts.gapX) + opts.paddingX * 2)
    const height = Math.max(160, y + opts.cellHeight + opts.paddingY + opts.paddingBottom)
    return { positions, width, height }
  },
}))
vi.mock('@/constants/enterpriseWorkflowEstablishment', () => ({
  ENTERPRISE_ORG_LAYERS: [
    { id: 'management', code: 'M', label: '管理层', color: '#2563eb' },
    { id: 'tools', code: 'T', label: '工具层', color: '#059669' },
    { id: 'execution', code: 'E', label: '执行层', color: '#d97706' },
    { id: 'service', code: 'S', label: '服务层', color: '#7c3aed' },
  ],
  resolveEnterpriseOrgLayer: (empId: string) => {
    if (empId.startsWith('mgmt')) return 'management'
    if (empId.startsWith('tool')) return 'tools'
    if (empId.startsWith('exec')) return 'execution'
    return 'service'
  },
}))
vi.mock('@/utils/typeGuards', () => ({
  asRecord: (v: unknown) => (v && typeof v === 'object' ? v as Record<string, unknown> : {}),
  asString: (v: unknown) => (typeof v === 'string' ? v : ''),
}))

import EnterpriseEstablishmentGraph from '@/components/workflow/EnterpriseEstablishmentGraph.vue'

const sampleDesks = [
  { empId: 'mgmt-001', shortName: '张三', panelTitle: '管理', enabled: true, snapshot: { visuallyBusy: false } },
  { empId: 'tool-001', shortName: '李四', panelTitle: '工具', enabled: true, snapshot: { visuallyBusy: true } },
  { empId: 'exec-001', shortName: '王五', panelTitle: '执行', enabled: false, snapshot: { visuallyBusy: false } },
  { empId: 'svc-001', shortName: '赵六', panelTitle: '服务', enabled: true, snapshot: { visuallyBusy: false } },
]

function mountComponent(propsOverrides = {}) {
  return mount(EnterpriseEstablishmentGraph, {
    props: {
      desks: sampleDesks,
      selectedEmpId: null,
      isBusy: (row: typeof sampleDesks[number]) => Boolean(row.snapshot?.visuallyBusy),
      ...propsOverrides,
    },
    global: {
      stubs: {
        VueFlow: true,
        Background: true,
        Controls: true,
        MiniMap: true,
      },
    },
  })
}

describe('EnterpriseEstablishmentGraph', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the root element with correct aria-label', () => {
    const wrapper = mountComponent()
    const root = wrapper.find('.ewg-root')
    expect(root.exists()).toBe(true)
    expect(root.attributes('aria-label')).toBe('企业四部门在岗节点图')
  })

  it('renders enterprise stack label when provided', () => {
    const wrapper = mountComponent({ enterpriseStackLabel: '家具行业包' })
    expect(wrapper.find('.ewg-stack-banner').exists()).toBe(true)
    expect(wrapper.text()).toContain('家具行业包')
  })

  it('does not render stack banner when no label', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.ewg-stack-banner').exists()).toBe(false)
  })

  it('emits select event on node click with valid empId', async () => {
    const wrapper = mountComponent()
    // Access component internals to test onNodeClick
    const vm = wrapper.vm as any
    vm.onNodeClick({ node: { id: 'management::mgmt-001', type: 'default', data: { empId: 'mgmt-001' } } })
    expect(wrapper.emitted('select')).toBeTruthy()
    expect(wrapper.emitted('select')![0]).toEqual(['mgmt-001'])
  })

  it('does not emit select for group node click', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.onNodeClick({ node: { id: 'zone-management', type: 'group', data: {} } })
    expect(wrapper.emitted('select')).toBeFalsy()
  })

  it('does not emit select for placeholder node click', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.onNodeClick({ node: { id: 'management::__empty__', type: 'default', data: { placeholder: true } } })
    expect(wrapper.emitted('select')).toBeFalsy()
  })

  it('handles empty desks list', () => {
    const wrapper = mountComponent({ desks: [] })
    expect(wrapper.find('.ewg-root').exists()).toBe(true)
  })

  it('parses empId from nodeId with :: separator', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    expect(vm.parseEmpIdFromNodeId('management::mgmt-001')).toBe('mgmt-001')
    expect(vm.parseEmpIdFromNodeId('no-double-colon')).toBeNull()
    expect(vm.parseEmpIdFromNodeId('a::b::c')).toBe('b::c')
  })

  it('generates zone node id correctly', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    expect(vm.zoneNodeId('management', 'mgmt-001')).toBe('management::mgmt-001')
  })

  it('computes flowNodes and flowEdges from desks', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    expect(vm.flowNodes.length).toBeGreaterThan(0)
    // 4 group nodes + 4 employee nodes = 8
    expect(vm.flowNodes.length).toBe(8)
  })

  it('marks selected employee node with correct style', () => {
    const wrapper = mountComponent({ selectedEmpId: 'mgmt-001' })
    const vm = wrapper.vm as any
    const selectedNode = vm.flowNodes.find((n: any) => n.data?.empId === 'mgmt-001')
    expect(selectedNode).toBeTruthy()
    expect(selectedNode.data.selected).toBe(true)
  })

  it('marks busy employee with gradient background', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    const busyNode = vm.flowNodes.find((n: any) => n.data?.empId === 'tool-001')
    expect(busyNode).toBeTruthy()
    expect(busyNode.data.busy).toBe(true)
    expect(busyNode.style.background).toContain('linear-gradient')
  })

  it('marks disabled employee with light background', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    const disabledNode = vm.flowNodes.find((n: any) => n.data?.empId === 'exec-001')
    expect(disabledNode).toBeTruthy()
    expect(disabledNode.data.enabled).toBe(false)
    expect(disabledNode.style.background).toContain('#f8fafc')
  })

  it('creates placeholder nodes for empty zones', () => {
    // Only management desks, other zones should have placeholders
    const wrapper = mountComponent({ desks: [sampleDesks[0]] })
    const vm = wrapper.vm as any
    const placeholders = vm.flowNodes.filter((n: any) => n.data?.placeholder)
    expect(placeholders.length).toBe(3) // tools, execution, service zones empty
  })
})
