import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref } from 'vue'

const wf2 = vi.hoisted(() => ({
  currentGraph: null as any,
  flowInstance: {
    applyNodeChanges: vi.fn(),
    applyEdgeChanges: vi.fn(),
    findNode: vi.fn(() => ({ position: { x: 320, y: 180 } })),
    screenToFlowCoordinate: vi.fn((p: { x: number; y: number }) => ({ x: p.x + 10, y: p.y + 20 })),
    project: vi.fn((p: { x: number; y: number }) => ({ x: p.x, y: p.y })),
    fitView: vi.fn(),
  },
  api: {
    workflowSandboxRun: vi.fn(async () => ({ ok: true, output: 'sandbox' })),
    executeWorkflow: vi.fn(async () => ({ id: 88 })),
    updateWorkflow: vi.fn(async () => ({ ok: true })),
    publishWorkflowVersion: vi.fn(async () => ({ version_no: 3 })),
    saveWorkflowAsTemplate: vi.fn(async () => ({ id: 77 })),
    listEmployees: vi.fn(async () => ({ employees: [{ id: 'emp-a', name: '员工A' }] })),
    listESkills: vi.fn(async () => ({ eskills: [{ id: 'skill-a', name: '技能A', domain: '销售' }] })),
  },
}))

vi.mock('@vue-flow/core', async () => {
  const vue = await import('vue')
  return {
    VueFlow: vue.defineComponent({
      name: 'VueFlow',
      emits: ['nodes-change', 'edges-change', 'node-drag-stop', 'node-click', 'pane-click', 'connect', 'edge-double-click'],
      setup(_, { slots }) {
        return () => vue.h('div', { class: 'vue-flow-stub' }, slots.default?.())
      },
    }),
    Handle: vue.defineComponent({ name: 'Handle', props: ['type', 'position', 'id'], setup: () => () => vue.h('span', { class: 'handle-stub' }) }),
    Position: { Left: 'left', Right: 'right' },
    useVueFlow: () => wf2.flowInstance,
  }
})

vi.mock('@vue-flow/background', async () => {
  const vue = await import('vue')
  return { Background: vue.defineComponent({ name: 'Background', setup: () => () => vue.h('div', { class: 'background-stub' }) }) }
})

vi.mock('@vue-flow/controls', async () => {
  const vue = await import('vue')
  return { Controls: vue.defineComponent({ name: 'Controls', setup: () => () => vue.h('div', { class: 'controls-stub' }) }) }
})

vi.mock('@vue-flow/minimap', async () => {
  const vue = await import('vue')
  return { MiniMap: vue.defineComponent({ name: 'MiniMap', setup: () => () => vue.h('div', { class: 'minimap-stub' }) }) }
})

vi.mock('./views/workflow/v2/composables/useWorkflowGraph', () => ({
  useWorkflowGraph: () => wf2.currentGraph,
}))

vi.mock('./api', () => ({ api: wf2.api }))

const VersionsPanelStub = defineComponent({
  name: 'VersionsPanel',
  emits: ['close', 'rolled-back'],
  setup(_, { emit }) {
    return () => h('button', { class: 'versions-rollback', onClick: () => emit('rolled-back', 2) }, 'rollback')
  },
})

function makeNode(id: string, kind: string, config: Record<string, unknown> = {}) {
  return {
    id,
    type: 'mod',
    position: { x: 10, y: 20 },
    data: {
      kind,
      label: `${kind}-${id}`,
      backendId: id,
      config,
    },
  }
}

function makeGraph() {
  const nodes = ref([
    makeNode('start', 'start', { output_var: 'start_result' }),
    makeNode('employee', 'employee', { employee_id: 'emp-a', output_var: 'employee_result' }),
  ])
  const edges = ref([{ id: 'edge-1', source: 'start', target: 'employee', sourceHandle: null }])
  const meta = ref({ name: '覆盖工作流', description: 'desc', is_active: false })
  return {
    nodes,
    edges,
    meta,
    loading: ref(false),
    saving: ref(false),
    loadGraph: vi.fn(async () => undefined),
    addNode: vi.fn(async (kind: string, position: { x: number; y: number }) => {
      const id = `node-${kind}-${nodes.value.length}`
      nodes.value.push(makeNode(id, kind, { position }))
      return id
    }),
    addEdge: vi.fn(async (source: string, target: string, sourceHandle?: string | null) => {
      edges.value.push({ id: `edge-${edges.value.length + 1}`, source, target, sourceHandle: sourceHandle ?? null })
    }),
    deleteEdge: vi.fn(async (id: string) => {
      edges.value = edges.value.filter((e) => e.id !== id)
    }),
    deleteNode: vi.fn(async (id: string) => {
      nodes.value = nodes.value.filter((n) => n.id !== id)
    }),
    updateNodePositionLocally: vi.fn((id: string, position: { x: number; y: number }) => {
      const n = nodes.value.find((node) => node.id === id)
      if (n) n.position = position
    }),
    flushNodePosition: vi.fn(async () => undefined),
    patchNodeData: vi.fn((id: string, patch: Record<string, unknown>) => {
      const n = nodes.value.find((node) => node.id === id)
      if (n) n.data = { ...n.data, ...patch }
    }),
    renameWorkflow: vi.fn(async (name: string, description?: string) => {
      meta.value = { ...meta.value, name, description: description || '' }
    }),
  }
}

async function flush() {
  await nextTick()
  await Promise.resolve()
  await nextTick()
}

beforeEach(() => {
  vi.useFakeTimers()
  wf2.currentGraph = makeGraph()
  for (const fn of Object.values(wf2.flowInstance)) {
    if (typeof fn === 'function' && 'mockClear' in fn) fn.mockClear()
  }
  for (const fn of Object.values(wf2.api)) fn.mockClear()
  Object.defineProperty(window, 'confirm', { configurable: true, value: vi.fn(() => true) })
  Object.defineProperty(window, 'prompt', { configurable: true, value: vi.fn(() => '覆盖输入') })
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('coverage workflow v2 editor', () => {
  it('drives editor toolbar, graph and canvas event branches', async () => {
    const [{ default: WorkflowFlowEditor }, { default: ToolbarPanel }, { default: PropertiesPanel }] = await Promise.all([
      import('./views/workflow/v2/WorkflowFlowEditor.vue'),
      import('./views/workflow/v2/panels/ToolbarPanel.vue'),
      import('./views/workflow/v2/panels/PropertiesPanel.vue'),
    ])

    const wrapper = mount(WorkflowFlowEditor, {
      props: { workflowId: 42 },
      global: { stubs: { VersionsPanel: VersionsPanelStub, Transition: false } },
    })
    await flush()
    expect(wf2.currentGraph.loadGraph).toHaveBeenCalledTimes(1)

    const toolbar = wrapper.findComponent(ToolbarPanel)
    await toolbar.vm.$emit('rename')
    expect(wf2.currentGraph.renameWorkflow).toHaveBeenCalledWith('覆盖输入', 'desc')
    await toolbar.vm.$emit('toggle-active')
    expect(wf2.api.updateWorkflow).toHaveBeenCalledWith(42, expect.any(String), expect.any(String), true)
    await toolbar.vm.$emit('sandbox')
    expect(wf2.api.workflowSandboxRun).toHaveBeenCalledWith(42, expect.objectContaining({ mock_employees: true }))
    await flush()
    expect(wrapper.text()).toContain('sandbox')
    await wrapper.find('.wf2-sandbox-panel button').trigger('click')
    await toolbar.vm.$emit('execute')
    expect(wf2.api.executeWorkflow).toHaveBeenCalledWith(42, {})
    await toolbar.vm.$emit('publish')
    expect(wf2.api.publishWorkflowVersion).toHaveBeenCalledWith(42, '覆盖输入')
    await toolbar.vm.$emit('versions')
    await wrapper.find('.versions-rollback').trigger('click')
    expect(wf2.currentGraph.loadGraph).toHaveBeenCalledTimes(2)
    await toolbar.vm.$emit('save-as-template')
    await flush()
    expect(wrapper.find('.wf2-tplcard').exists()).toBe(true)
    await wrapper.find('.wf2-tplcard__foot .wf2-tb-btn--primary').trigger('click')
    expect(wf2.api.saveWorkflowAsTemplate).toHaveBeenCalledWith(42, expect.objectContaining({ name: expect.stringContaining('覆盖输入') }))

    const vueFlow = wrapper.findComponent({ name: 'VueFlow' })
    await vueFlow.vm.$emit('nodes-change', [{ id: 'start', type: 'select' }])
    expect(wf2.flowInstance.applyNodeChanges).toHaveBeenCalled()
    await vueFlow.vm.$emit('edges-change', [{ id: 'edge-1', type: 'select' }])
    expect(wf2.flowInstance.applyEdgeChanges).toHaveBeenCalled()
    await vueFlow.vm.$emit('node-click', { node: wf2.currentGraph.nodes.value[1] })
    await flush()
    expect(wrapper.findComponent(PropertiesPanel).props('selected')?.id).toBe('employee')
    await vueFlow.vm.$emit('node-drag-stop', { node: wf2.currentGraph.nodes.value[1] })
    expect(wf2.currentGraph.updateNodePositionLocally).toHaveBeenCalledWith('employee', { x: 320, y: 180 })
    expect(wf2.currentGraph.flushNodePosition).toHaveBeenCalledWith('employee')
    await vueFlow.vm.$emit('connect', { source: 'start', target: 'employee', sourceHandle: 'ok' })
    expect(wf2.currentGraph.addEdge).toHaveBeenCalledWith('start', 'employee', 'ok')
    await vueFlow.vm.$emit('connect', { source: '', target: 'employee' })
    await vueFlow.vm.$emit('edge-double-click', { edge: { id: 'edge-1' } })
    expect(wf2.currentGraph.deleteEdge).toHaveBeenCalledWith('edge-1')
    await vueFlow.vm.$emit('pane-click')
    expect(wrapper.findComponent(PropertiesPanel).props('selected')).toBeNull()

    const library = wrapper.findComponent({ name: 'NodeLibraryPanel' })
    await library.vm.$emit('add', 'condition')
    expect(wf2.currentGraph.addNode).toHaveBeenCalledWith('condition', expect.objectContaining({ x: expect.any(Number), y: expect.any(Number) }))
    const canvas = wrapper.find('.wf2-canvas-wrap')
    const dragEvent = { types: ['application/wf2-node-kind'], dropEffect: '', getData: vi.fn(() => 'variable_set') }
    await canvas.trigger('dragover', { dataTransfer: dragEvent })
    await canvas.trigger('drop', { dataTransfer: dragEvent, clientX: 50, clientY: 60 })
    expect(wf2.flowInstance.screenToFlowCoordinate).toHaveBeenCalledWith({ x: 50, y: 60 })

    await toolbar.vm.$emit('auto-layout')
    await flush()
    expect(wf2.currentGraph.flushNodePosition).toHaveBeenCalled()
    expect(wf2.flowInstance.fitView).toHaveBeenCalledWith({ padding: 0.18 })

    const properties = wrapper.findComponent(PropertiesPanel)
    await vueFlow.vm.$emit('node-click', { node: wf2.currentGraph.nodes.value[0] })
    await properties.vm.$emit('patch', { id: 'start', label: '新名称', config: { output_var: 'x' } })
    expect(wf2.currentGraph.patchNodeData).toHaveBeenCalledWith('start', { label: '新名称', config: { output_var: 'x' } })
    await properties.vm.$emit('delete', 'start')
    expect(wf2.currentGraph.deleteNode).toHaveBeenCalledWith('start')

    wrapper.unmount()
  })

  it('covers empty/error editor branches without breaking the shell', async () => {
    const { default: WorkflowFlowEditor } = await import('./views/workflow/v2/WorkflowFlowEditor.vue')
    wf2.currentGraph.nodes.value = []
    wf2.currentGraph.loadGraph.mockRejectedValueOnce({ detail: { reason: 'bad graph' } })
    wf2.currentGraph.addNode.mockRejectedValueOnce(new Error('add failed'))
    wf2.api.workflowSandboxRun.mockRejectedValueOnce(new Error('sandbox failed'))

    const wrapper = mount(WorkflowFlowEditor, {
      props: { workflowId: 12 },
      global: { stubs: { VersionsPanel: VersionsPanelStub, Transition: false } },
    })
    await flush()
    expect(wrapper.text()).toContain('加载失败')
    await wrapper.findComponent({ name: 'ToolbarPanel' }).vm.$emit('publish')
    expect(wrapper.text()).toContain('画布为空')
    await wrapper.findComponent({ name: 'ToolbarPanel' }).vm.$emit('save-as-template')
    expect(wrapper.text()).toContain('画布为空')
    await wrapper.findComponent({ name: 'ToolbarPanel' }).vm.$emit('sandbox')
    await flush()
    expect(wrapper.text()).toContain('沙盒运行失败')
    await wrapper.findComponent({ name: 'NodeLibraryPanel' }).vm.$emit('add', 'employee')
    await flush()
    expect(wrapper.text()).toContain('添加节点失败')
    wrapper.unmount()
  })
})

describe('coverage workflow v2 panels and nodes', () => {
  it('covers toolbar event surface', async () => {
    const { default: ToolbarPanel } = await import('./views/workflow/v2/panels/ToolbarPanel.vue')
    const wrapper = mount(ToolbarPanel, { props: { workflowName: '', saving: true, isActive: true } })
    expect(wrapper.text()).toContain('未命名工作流')
    for (const button of wrapper.findAll('button')) await button.trigger('click')
    await wrapper.find('h2').trigger('click')
    expect(Object.keys(wrapper.emitted())).toEqual(expect.arrayContaining([
      'back', 'toggle-active', 'auto-layout', 'versions', 'publish', 'save-as-template', 'sandbox', 'execute', 'rename',
    ]))
  })

  it('covers generic node summaries for every node kind branch', async () => {
    const { default: GenericNode } = await import('./views/workflow/v2/nodes/GenericNode.vue')
    const cases = [
      ['employee', { employee_id: 'emp-a' }, '员工 emp-a'],
      ['employee', {}, '未选择员工'],
      ['eskill', { skill_id: 'skill-a' }, 'ESkill skill-a'],
      ['condition', { expression: 'x > 3 && y < 9' }, 'x > 3'],
      ['openapi_operation', { connector_id: 'crm', operation_id: 'create' }, 'crm#create'],
      ['knowledge_search', { kb_id: 'kb-a' }, 'KB kb-a'],
      ['webhook_trigger', { secret: 's' }, '含独立密钥'],
      ['webhook_trigger', {}, '使用全局密钥'],
      ['cron_trigger', { cron: '0 9 * * *' }, '0 9'],
      ['variable_set', { name: 'amount' }, 'amount ='],
      ['delay', {}, '未注册的节点类型'],
    ]
    for (const [kind, config, expected] of cases) {
      const wrapper = mount(GenericNode, {
        props: { id: `n-${kind}`, selected: true, data: { kind, label: `${kind} 节点`, config } },
        global: { stubs: { Handle: defineComponent({ template: '<span />' }) } },
      })
      expect(wrapper.text()).toContain(String(expected))
      wrapper.unmount()
    }
  })

  it('covers properties panel field editors and API loading fallbacks', async () => {
    const { default: PropertiesPanel } = await import('./views/workflow/v2/panels/PropertiesPanel.vue')
    const selected = makeNode('selected-employee', 'employee', { employee_id: 'emp-a', output_var: 'out' })
    const wrapper = mount(PropertiesPanel, { props: { selected } })
    await flush()
    await wrapper.find('input[type="text"]').setValue('更新节点')
    await wrapper.find('input[type="text"]').trigger('blur')
    expect(wrapper.emitted('patch')?.length).toBeGreaterThan(0)
    for (const input of wrapper.findAll('input')) {
      await input.setValue('42').catch(() => undefined)
      await input.trigger('change').catch(() => undefined)
    }
    for (const select of wrapper.findAll('select')) await select.setValue('emp-a').catch(() => undefined)
    for (const textarea of wrapper.findAll('textarea')) await textarea.setValue('{"ok":true}').catch(() => undefined)
    await wrapper.find('.wf2-properties__del').trigger('click')
    expect(wrapper.emitted('delete')?.[0]).toEqual(['selected-employee'])
    await wrapper.setProps({ selected: makeNode('selected-skill', 'eskill', { skill_id: 'skill-a', params: { a: 1 } }) })
    await flush()
    for (const select of wrapper.findAll('select')) await select.setValue('skill-a').catch(() => undefined)
    await wrapper.setProps({ selected: null })
    await flush()
    expect(wrapper.text()).toContain('选中一个节点')
    wrapper.unmount()

    wf2.api.listEmployees.mockRejectedValueOnce(new Error('employees failed'))
    wf2.api.listESkills.mockRejectedValueOnce(new Error('skills failed'))
    const failed = mount(PropertiesPanel, { props: { selected: makeNode('selected-failed', 'employee', {}) } })
    await flush()
    expect(failed.exists()).toBe(true)
    failed.unmount()
  })

  it('covers variable inference and manual variable editing', async () => {
    const { default: VariablesPanel } = await import('./views/workflow/v2/panels/VariablesPanel.vue')
    const wrapper = mount(VariablesPanel, {
      props: {
        nodes: [
          makeNode('n1', 'employee', { output_var: 'reply' }),
          makeNode('n2', 'variable_set', { name: 'customer_name', value: '张三' }),
        ],
      },
    })
    expect(wrapper.text()).toContain('{{ reply }}')
    expect(wrapper.text()).toContain('{{ customer_name }}')
    await wrapper.find('.btn-add').trigger('click')
    await wrapper.find('.var-edit input').setValue('manual value')
    expect((wrapper.find('.var-edit input').element as HTMLInputElement).value).toBe('manual value')
    await wrapper.find('.btn-remove').trigger('click')
    await wrapper.setProps({ nodes: [] })
    await flush()
    expect(wrapper.text()).toContain('暂无变量')
  })
})
