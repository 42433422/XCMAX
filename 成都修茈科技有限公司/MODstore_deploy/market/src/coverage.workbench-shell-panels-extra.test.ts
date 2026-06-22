import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  llmStatus: vi.fn(),
  llmCatalog: vi.fn(),
  getEmployeeManifest: vi.fn(),
  employeeSaveManifest: vi.fn(),
  listEmployees: vi.fn(),
  adminDeleteEmployeePack: vi.fn(),
  adminPurgeAllEmployeePacks: vi.fn(),
  workbenchResearchContext: vi.fn(),
  executeEmployeeTask: vi.fn(),
  employeeBenchTest: vi.fn(),
  employeePublish: vi.fn(),
  employeeExportZip: vi.fn(),
  employeeSyncTest: vi.fn(),
}))

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  hasRoute: vi.fn(() => true),
}))

const routeMock = vi.hoisted(() => ({
  params: { target: 'employee', id: 'emp_route' },
  query: {} as Record<string, unknown>,
}))

const authMock = vi.hoisted(() => ({
  isAdmin: true,
  username: 'admin',
}))

const fitViewMock = vi.hoisted(() => vi.fn())
const computeAutoLayoutMock = vi.hoisted(() => vi.fn())
const fieldAssistMock = vi.hoisted(() => vi.fn())
const ttsSpeakMock = vi.hoisted(() => vi.fn())
const runEmployeeDraftMock = vi.hoisted(() => vi.fn())

const manifestHelpers = vi.hoisted(() => ({
  manifestToNodes: vi.fn(),
  manifestToEdges: vi.fn(),
  addModuleToManifest: vi.fn(),
  removeModuleFromManifest: vi.fn(),
}))

const workbenchStore = vi.hoisted(() => ({
  target: {
    kind: 'employee',
    id: 'emp_1',
    name: 'Employee One',
    manifest: {} as Record<string, any>,
  },
  canvasNodes: [] as any[],
  canvasEdges: [] as any[],
  selectedNode: null as any,
  inspectorMode: 'node',
  dirty: false,
  lastSavedAt: 0,
  agentRuns: [] as any[],
  currentRun: null as any,
  setTarget: vi.fn((kind: string, id: string | null, manifest: Record<string, unknown>, name: string) => {
    workbenchStore.target.kind = kind
    workbenchStore.target.id = id
    workbenchStore.target.manifest = manifest
    workbenchStore.target.name = name
  }),
  patchManifest: vi.fn((path: string, value: unknown) => {
    const parts = path.split('.')
    let cur = workbenchStore.target.manifest as Record<string, any>
    for (const key of parts.slice(0, -1)) {
      if (!cur[key] || typeof cur[key] !== 'object') cur[key] = {}
      cur = cur[key]
    }
    cur[parts[parts.length - 1]] = value
    workbenchStore.dirty = true
  }),
  setCanvasGraph: vi.fn((nodes: any[], edges: any[]) => {
    workbenchStore.canvasNodes = nodes
    workbenchStore.canvasEdges = edges
  }),
  selectNode: vi.fn((id: string | null) => {
    workbenchStore.selectedNode = id ? workbenchStore.canvasNodes.find((n) => n.id === id) ?? { id, data: {} } : null
  }),
  loadEligibleWorkflows: vi.fn(),
  setResearch: vi.fn(),
}))

const breakpointState = vi.hoisted(() => ({
  isMobile: { value: false },
}))

function baseManifest() {
  return {
    identity: { id: 'emp_1', name: 'Employee One', version: '1.0.0', description: 'desc' },
    cognition: {
      agent: {
        system_prompt: 'Help users',
        role: { name: 'Helper', persona: 'Helpful', tone: 'friendly', expertise: [] },
        model: { provider: 'deepseek', model_name: 'deepseek-chat', temperature: 0.5 },
      },
      skills: [{ id: 'skill_a' }],
    },
    collaboration: { workflow: { workflow_id: 12, name: 'Flow' } },
    memory: { long_term: true },
  }
}

function resetWorkbenchStore() {
  workbenchStore.target.kind = 'employee'
  workbenchStore.target.id = 'emp_1'
  workbenchStore.target.name = 'Employee One'
  workbenchStore.target.manifest = baseManifest()
  workbenchStore.canvasNodes = [
    {
      id: 'identity',
      position: { x: 0, y: 0 },
      data: {
        moduleKind: 'identity',
        label: 'Identity',
        enabled: true,
        meta: { label: 'Identity', icon: 'I', accent: '#111', required: true, paths: ['identity'] },
        slice: workbenchStore.target.manifest.identity,
      },
    },
  ]
  workbenchStore.canvasEdges = []
  workbenchStore.selectedNode = workbenchStore.canvasNodes[0]
  workbenchStore.inspectorMode = 'node'
  workbenchStore.dirty = false
  workbenchStore.agentRuns = []
  workbenchStore.currentRun = null
  workbenchStore.lastSavedAt = 0
}

vi.mock('./api', () => ({ api: apiMock }))
vi.mock('./stores/workbench', () => ({ useWorkbenchStore: () => workbenchStore }))
vi.mock('./stores/auth', () => ({ useAuthStore: () => authMock }))
vi.mock('pinia', () => ({
  storeToRefs: (store: Record<string, unknown>) =>
    Object.fromEntries(
      Object.entries(store)
        .filter(([, value]) => typeof value !== 'function')
        .map(([key, value]) => [key, { value }]),
    ),
}))
vi.mock('vue-router', () => ({
  useRouter: () => routerMock,
  useRoute: () => routeMock,
  RouterLink: { props: ['to'], template: '<a><slot /></a>' },
}))
vi.mock('@vue-flow/core', () => ({
  VueFlow: { template: '<div class="vue-flow"><slot /><slot name="node-employeeModule" /></div>' },
  Handle: { template: '<span class="handle" />' },
  Position: { Left: 'left', Right: 'right' },
  useVueFlow: vi.fn(() => ({ fitView: fitViewMock })),
}))
vi.mock('@vue-flow/background', () => ({ Background: { template: '<div class="bg" />' } }))
vi.mock('@vue-flow/controls', () => ({ Controls: { template: '<div class="controls" />' } }))
vi.mock('@vue-flow/minimap', () => ({ MiniMap: { template: '<div class="minimap" />' } }))
vi.mock('./views/workflow/v2/WorkflowFlowEditor.vue', () => ({
  default: { props: ['workflowId'], emits: ['back'], template: '<div class="workflow-editor" />' },
}))
vi.mock('./views/workflow/v2/composables/useAutoLayout', () => ({
  computeAutoLayout: computeAutoLayoutMock,
}))
vi.mock('./composables/useWorkbenchManifest', () => ({
  MODULE_META: {
    identity: { label: 'Identity', icon: 'I', accent: '#111', required: true, paths: ['identity'] },
    prompt: { label: 'Prompt', icon: 'P', accent: '#222', required: true, paths: ['cognition.agent'] },
    skills: { label: 'Skills', icon: 'S', accent: '#333', required: false, paths: ['cognition.skills'] },
    workflow_heart: { label: 'Workflow', icon: 'W', accent: '#444', required: false, paths: ['collaboration.workflow'] },
    memory: { label: 'Memory', icon: 'M', accent: '#555', required: false, paths: ['memory'] },
  },
  DEFAULT_MODULE_ORDER: ['identity', 'prompt', 'skills', 'workflow_heart', 'memory'],
  manifestToNodes: manifestHelpers.manifestToNodes,
  manifestToEdges: manifestHelpers.manifestToEdges,
  addModuleToManifest: manifestHelpers.addModuleToManifest,
  removeModuleFromManifest: manifestHelpers.removeModuleFromManifest,
}))
vi.mock('./employeeConfigV2', () => ({
  createEmptyEmployeeConfigV2: vi.fn((opts?: Record<string, unknown>) => ({
    identity: { id: '', name: '', version: '1.0.0' },
    cognition: { agent: { model: (opts as any)?.model || { provider: 'auto', model_name: 'auto' } } },
    collaboration: { workflow: { workflow_id: 0 } },
  })),
  upgradeLegacyToV2: vi.fn((raw: Record<string, unknown>) => ({
    identity: { id: raw.id || '', name: raw.name || '', version: raw.version || '1.0.0' },
    cognition: { agent: { role: {}, model: {} } },
    collaboration: { workflow: {} },
  })),
}))
vi.mock('./domain/llm/defaultEmployeeLlm', () => ({
  AUTO_EMPLOYEE_LLM_SENTINEL: 'auto',
  STATIC_DEFAULT_EMPLOYEE_LLM: { provider: 'auto', model_name: 'auto' },
  resolveDefaultEmployeeLlmFromStatusAndCatalog: vi.fn(() => ({ provider: 'deepseek', model_name: 'deepseek-chat' })),
}))
vi.mock('./composables/useBreakpoint', () => ({ useBreakpoint: () => ({ isMobile: breakpointState.isMobile }) }))
vi.mock('./composables/useAgentLoop', () => ({ useAgentLoop: () => ({ runEmployeeDraft: runEmployeeDraftMock }) }))
vi.mock('./composables/useFieldAi', () => ({ useFieldAi: () => ({ assist: fieldAssistMock }) }))
vi.mock('./composables/useManifestDiff', () => ({
  useManifestDiff: () => ({ hasBaseline: { value: true }, diffCount: { value: 2 }, diffs: { value: [] } }),
}))
vi.mock('./composables/useStreamingTts', () => ({
  useStreamingTts: vi.fn(() => ({ speak: ttsSpeakMock })),
}))
vi.mock('./composables/llmCatalogModelHelpers', () => ({
  LLM_CATEGORY_ORDER: ['chat', 'reasoning'],
  categoryLabel: vi.fn((_catalog: unknown, cat: string) => `cat:${cat}`),
  modelsForCategory: vi.fn((block: any, cat: string) =>
    (block?.models_detailed || []).filter((m: any) => (m.capability?.category || 'chat') === cat),
  ),
  modelOptionLabel: vi.fn((row: any) => `model:${row.id}`),
}))

import WorkbenchShell from './views/workbench/WorkbenchShell.vue'
import CanvasStage from './views/workbench/panels/CanvasStage.vue'
import LeftRail from './views/workbench/panels/LeftRail.vue'
import RightRail from './views/workbench/panels/RightRail.vue'
import EmployeeModuleNode from './views/workbench/nodes/EmployeeModuleNode.vue'

const globalMount = {
  global: {
    stubs: {
      RouterLink: { props: ['to'], template: '<a><slot /></a>' },
      Teleport: true,
      Transition: false,
      TransitionGroup: false,
      CanvasStage: { template: '<div class="canvas-stage-stub" />', methods: { fitView: fitViewMock } },
      EmployeeAiDraftReview: { template: '<div class="draft-review-stub" />' },
    },
  },
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
  sessionStorage.clear()
  localStorage.clear()
  document.body.innerHTML = ''
  resetWorkbenchStore()
  breakpointState.isMobile.value = false
  routeMock.params = { target: 'employee', id: 'emp_route' }
  routeMock.query = {}
  authMock.isAdmin = true
  authMock.username = 'admin'

  computeAutoLayoutMock.mockImplementation((nodes: any[]) => new Map(nodes.map((n, i) => [n.id, { x: i * 10, y: i * 20 }])))
  manifestHelpers.manifestToNodes.mockImplementation((manifest: Record<string, any>) => [
    {
      id: 'identity',
      position: { x: 0, y: 0 },
      data: {
        moduleKind: 'identity',
        label: 'Identity',
        enabled: true,
        meta: { label: 'Identity', icon: 'I', accent: '#111', required: true, paths: ['identity'] },
        slice: manifest.identity,
      },
    },
    {
      id: 'prompt',
      position: { x: 0, y: 0 },
      data: {
        moduleKind: 'prompt',
        label: 'Prompt',
        enabled: true,
        meta: { label: 'Prompt', icon: 'P', accent: '#222', required: true, paths: ['cognition.agent'] },
        slice: manifest.cognition?.agent,
      },
    },
  ])
  manifestHelpers.manifestToEdges.mockImplementation((nodes: any[]) => nodes.length > 1 ? [{ id: 'e-identity-prompt', source: 'identity', target: 'prompt' }] : [])
  manifestHelpers.addModuleToManifest.mockImplementation((manifest: Record<string, unknown>, kind: string) => ({ ...manifest, [`added_${kind}`]: true }))
  manifestHelpers.removeModuleFromManifest.mockImplementation((manifest: Record<string, unknown>, kind: string) => ({ ...manifest, [`removed_${kind}`]: true }))

  apiMock.llmStatus.mockResolvedValue({ providers: [] })
  apiMock.llmCatalog.mockResolvedValue({
    providers: [
      { provider: 'deepseek', label: 'DeepSeek', models: ['deepseek-chat'], models_detailed: [{ id: 'deepseek-chat', capability: { category: 'chat' } }] },
      { provider: 'openai', label: 'OpenAI', models: ['gpt-test'], models_detailed: [{ id: 'gpt-test', capability: { category: 'reasoning' } }] },
    ],
  })
  apiMock.getEmployeeManifest.mockResolvedValue({
    pack_id: 'emp_loaded',
    name: 'Loaded Employee',
    manifest: baseManifest(),
  })
  apiMock.employeeSaveManifest.mockResolvedValue({ ok: true, pack_id: 'emp_saved', eskill_registered: 1, manifest: baseManifest() })
  apiMock.listEmployees.mockResolvedValue([
    { id: 'emp_1', name: 'Employee One', source: 'catalog' },
    { id: 'emp_old', name: 'Old Employee', source: 'v1_catalog' },
  ])
  apiMock.adminDeleteEmployeePack.mockResolvedValue({})
  apiMock.adminPurgeAllEmployeePacks.mockResolvedValue({ removed_packages_json: 1, removed_db_rows: 2, removed_files: 3 })
  apiMock.workbenchResearchContext.mockResolvedValue({ context: 'research', sources: ['s1'] })
  apiMock.executeEmployeeTask.mockResolvedValue({ ok: true, text: 'done' })
  apiMock.employeeBenchTest.mockResolvedValue({
    ok: true,
    tasks_result: [],
    level_scores: { 1: 90 },
    overall_score: 90,
    audit: { ok: true, dimensions: { manifest_compliance: { score: 90, reasons: [] } }, summary: { average: 90, pass: true } },
    passed: true,
  })
  apiMock.employeePublish.mockResolvedValue({ ok: true, pkg_id: 'emp_1' })
  apiMock.employeeExportZip.mockResolvedValue(new Blob(['zip']))
  apiMock.employeeSyncTest.mockResolvedValue({ ok: true, stage: 'done', bench: { passed: true } })
  fieldAssistMock.mockResolvedValue({ value: 'Refined prompt', explanation: 'clearer' })
  ttsSpeakMock.mockResolvedValue(undefined)
  runEmployeeDraftMock.mockResolvedValue({ abort: vi.fn() })

  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:pack') })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  vi.stubGlobal('confirm', vi.fn(() => true))
  vi.stubGlobal('alert', vi.fn())
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('employee module node coverage', () => {
  it('renders all summary branches', () => {
    const meta = { label: 'Fallback', icon: 'F', accent: '#000', required: false }
    const cases = [
      [{ moduleKind: 'identity', label: 'Identity', meta, slice: { name: 'Alice' }, enabled: true }, 'Alice'],
      [{ moduleKind: 'identity', label: 'Identity', meta, slice: { id: 'emp_x' }, enabled: false }, 'emp_x'],
      [{ moduleKind: 'prompt', label: 'Prompt', meta, slice: { system_prompt: 'x'.repeat(70) }, enabled: true }, '…'],
      [{ moduleKind: 'prompt', label: 'Prompt', meta, slice: {}, enabled: true }, '未填写提示词'],
      [{ moduleKind: 'skills', label: 'Skills', meta, slice: [{ id: 'a' }, { id: 'b' }], enabled: true }, '2 个技能'],
      [{ moduleKind: 'skills', label: 'Skills', meta, slice: [], enabled: true }, '暂无技能'],
      [{ moduleKind: 'workflow_heart', label: 'Workflow', meta, slice: { workflow_id: 8 }, enabled: true }, '工作流 #8'],
      [{ moduleKind: 'workflow_heart', label: 'Workflow', meta, slice: {}, enabled: true }, '未绑定工作流'],
      [{ moduleKind: 'memory', label: 'Memory', meta, slice: { long_term: true }, enabled: true }, '短期 + 长期记忆'],
      [{ moduleKind: 'memory', label: 'Memory', meta, slice: {}, enabled: true }, '仅短期记忆'],
      [{ moduleKind: 'other', label: 'Other', meta, slice: { x: 1 }, enabled: true }, 'Fallback'],
      [{ moduleKind: 'other', label: 'Other', meta, slice: null, enabled: true }, '未配置'],
    ] as any[]

    for (const [data, expected] of cases) {
      const wrapper = mount(EmployeeModuleNode, { props: { id: 'n1', selected: true, data }, global: { stubs: { Handle: true } } })
      expect(wrapper.text()).toContain(expected)
      wrapper.unmount()
    }
  })
})

describe('workbench canvas and rails coverage', () => {
  it('covers canvas sync, graph events, drop and exposed layout helpers', async () => {
    const wrapper = mount(CanvasStage, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    expect(workbenchStore.setCanvasGraph).toHaveBeenCalled()
    expect(workbenchStore.canvasNodes[0].position).toEqual({ x: 0, y: 0 })

    vm.onNodesChange([{ type: 'position', id: 'identity', position: { x: 5, y: 6 } }])
    expect(workbenchStore.canvasNodes[0].position).toEqual({ x: 5, y: 6 })
    vm.onNodesChange([{ type: 'remove', id: 'identity' }])
    expect(workbenchStore.target.manifest.removed_identity).toBe(true)

    vm.onConnect({ source: 'identity', target: 'prompt' })
    expect(workbenchStore.canvasEdges.at(-1).id).toBe('e-identity-prompt')
    vm.onNodeClick({ node: { id: 'prompt' } })
    expect(workbenchStore.selectNode).toHaveBeenCalledWith('prompt')
    vm.onPaneClick()
    expect(workbenchStore.selectNode).toHaveBeenCalledWith(null)

    const dragEvent = { preventDefault: vi.fn(), dataTransfer: { dropEffect: '', getData: vi.fn(() => 'memory') } }
    vm.onDragOver(dragEvent)
    expect(dragEvent.preventDefault).toHaveBeenCalled()
    expect(dragEvent.dataTransfer.dropEffect).toBe('copy')
    vm.onDrop(dragEvent)
    expect(workbenchStore.target.manifest.added_memory).toBe(true)
    expect(workbenchStore.dirty).toBe(true)

    vm.fitView()
    expect(fitViewMock).toHaveBeenCalledWith({ padding: 0.15, duration: 400 })
    vi.useFakeTimers()
    vm.autoLayout()
    await vi.advanceTimersByTimeAsync(80)
    expect(fitViewMock).toHaveBeenCalled()
  })

  it('covers canvas workflow and non-employee computed branches', async () => {
    workbenchStore.target.kind = 'workflow'
    workbenchStore.target.id = '44'
    const workflow = mount(CanvasStage, globalMount)
    await flushPromises()
    expect((workflow.vm as any).isWorkflowTarget).toBe(true)
    expect((workflow.vm as any).activeWorkflowId).toBe(44)
    workflow.unmount()

    workbenchStore.target.kind = 'mod'
    workbenchStore.target.id = null
    const mod = mount(CanvasStage, globalMount)
    await flushPromises()
    expect((mod.vm as any).isEmployeeTarget).toBe(false)
  })

  it('covers left rail list, agent, delete, purge and route selection flows', async () => {
    routeMock.query = { packId: 'emp_1' }
    workbenchStore.currentRun = { brief: 'retry brief' }
    workbenchStore.agentRuns = [{ id: 'run1', brief: 'brief', startedAt: 1, status: 'done', manifest: { identity: { id: 'generated' } } }]
    const wrapper = mount(LeftRail, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.visibleEmployees.map((e: any) => e.id)).toContain('emp_1')
    expect(wrapper.emitted('select-employee')?.[0]).toEqual(['emp_1'])
    vm.hideLocally('emp_1')
    expect([...vm.hiddenPkgIds]).toContain('emp_1')
    vm.clearHiddenPkgIds()
    expect([...vm.hiddenPkgIds]).toHaveLength(0)
    vm.selectEmployee('emp_1')
    expect(wrapper.emitted('select-employee')?.at(-1)).toEqual(['emp_1'])

    vm.useSuggestion('make employee')
    expect(vm.agentInput).toBe('make employee')
    vm.agentInput = 'draft employee'
    await vm.runAgentDraft()
    expect(runEmployeeDraftMock).toHaveBeenCalledWith('draft employee')
    expect(vm.view).toBe('agent')

    await vm.retryEmployeeDraft()
    expect(runEmployeeDraftMock).toHaveBeenCalledWith('retry brief')
    vm.currentAbort = vi.fn()
    vm.abortCurrentRun()
    expect(vm.agentRunning).toBe(false)

    vm.applyRunManifest(workbenchStore.agentRuns[0])
    expect(workbenchStore.setTarget).toHaveBeenCalledWith('employee', 'emp_1', { identity: { id: 'generated' } }, 'Employee One')
    expect(vm.formatTs(Date.now())).toBeTruthy()

    ;(window.confirm as any).mockReturnValueOnce(false)
    await vm.confirmDeleteEmployee({ id: 'emp_1', name: 'Employee One' })
    expect(apiMock.adminDeleteEmployeePack).not.toHaveBeenCalled()
    ;(window.confirm as any).mockReturnValueOnce(true)
    await vm.confirmDeleteEmployee({ id: 'emp_1', name: 'Employee One' })
    expect(apiMock.adminDeleteEmployeePack).toHaveBeenCalledWith('emp_1')

    ;(window.confirm as any).mockReturnValueOnce(true)
    await vm.purgeAllEmployees()
    expect(apiMock.adminPurgeAllEmployeePacks).toHaveBeenCalled()
    expect(vm.listError).toContain('packages.json')
  })

  it('covers left rail error and non-admin branches', async () => {
    apiMock.listEmployees.mockRejectedValueOnce(new Error('list failed'))
    const wrapper = mount(LeftRail, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.listError).toContain('list failed')

    apiMock.adminDeleteEmployeePack.mockRejectedValueOnce(new Error('delete failed'))
    await vm.confirmDeleteEmployee({ id: 'emp_1', name: 'Employee One' })
    expect(vm.listError).toContain('delete failed')

    apiMock.adminPurgeAllEmployeePacks.mockRejectedValueOnce(new Error('purge failed'))
    await vm.purgeAllEmployees()
    expect(vm.listError).toContain('purge failed')

    authMock.isAdmin = false
    await vm.confirmDeleteEmployee({ id: 'emp_1', name: 'Employee One' })
  })
})

describe('workbench right rail coverage', () => {
  it('covers identity/prompt fields, LLM catalog, refine, research, run and TTS', async () => {
    localStorage.setItem('modstore_token', 'token')
    workbenchStore.selectedNode = {
      id: 'prompt',
      data: {
        moduleKind: 'prompt',
        label: 'Prompt',
        meta: { label: 'Prompt', icon: 'P', accent: '#222', required: true, paths: ['cognition.agent'] },
      },
    }
    const wrapper = mount(RightRail, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.mode).toBe('node')
    expect(vm.identityName).toBe('Employee One')
    vm.identityName = 'Updated'
    expect(workbenchStore.patchManifest).toHaveBeenCalledWith('identity.name', 'Updated')
    vm.temperature = 0.9
    expect(workbenchStore.target.manifest.cognition.agent.model.temperature).toBe(0.9)

    await vm.refreshWorkbenchLlmCatalog()
    expect(apiMock.llmCatalog).toHaveBeenCalledWith(true)
    expect(vm.catalogProviderPickerRows.map((r: any) => r.provider)).toContain('deepseek')
    expect(vm.employeeHasStructuredModels).toBe(true)
    expect(vm.employeeCategoryLabel('chat')).toBe('cat:chat')
    expect(vm.employeeModelsForCategory('chat')).toHaveLength(1)
    expect(vm.employeeModelOptionLabel({ id: 'x' })).toBe('model:x')
    vm.modelProvider = 'auto'
    vm.onEmployeeLlmProviderPicked()
    expect(workbenchStore.patchManifest).toHaveBeenCalledWith('cognition.agent.model.provider', 'auto')

    localStorage.removeItem('modstore_token')
    apiMock.llmCatalog.mockClear()
    await vm.refreshWorkbenchLlmCatalog()
    expect(apiMock.llmCatalog).not.toHaveBeenCalled()
    localStorage.setItem('modstore_token', 'token')

    await vm.refinePrompt()
    expect(fieldAssistMock).toHaveBeenCalled()
    expect(vm.refineResult).toBe('Refined prompt')
    vm.applyRefine()
    expect(workbenchStore.target.manifest.cognition.agent.system_prompt).toBe('Refined prompt')

    apiMock.workbenchResearchContext.mockClear()
    workbenchStore.target.manifest.identity.name = ''
    workbenchStore.target.name = ''
    vm.identityName = ''
    vm.researchBrief = ''
    await flushPromises()
    await vm.fetchResearch()
    expect(apiMock.workbenchResearchContext).not.toHaveBeenCalled()
    vm.researchBrief = 'market'
    await vm.fetchResearch()
    expect(workbenchStore.setResearch).toHaveBeenCalledWith('research', ['s1'])

    vm.runInput = 'hello'
    await vm.runEmployee()
    expect(apiMock.executeEmployeeTask).toHaveBeenCalledWith('emp_1', 'hello', {})
    expect(vm.runResult).toContain('"ok": true')

    await vm.previewTts()
    expect(ttsSpeakMock).toHaveBeenCalledWith('你好，我是您的 AI 助理')
  })

  it('covers right rail module, publish, download and sync flows', async () => {
    vi.useFakeTimers()
    const wrapper = mount(RightRail, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.presentModuleKinds.has('identity')).toBe(true)
    vm.addModule('memory')
    expect(workbenchStore.target.manifest.added_memory).toBe(true)
    const drag = { dataTransfer: { setData: vi.fn() } }
    vm.dragModuleStart('skills', drag)
    expect(drag.dataTransfer.setData).toHaveBeenCalledWith('application/emp-module-kind', 'skills')

    await vm.startBenchTest()
    expect(apiMock.employeeBenchTest).toHaveBeenCalledWith('emp_1')
    expect(vm.publishState).toBe('done')
    await vi.advanceTimersByTimeAsync(1000)
    expect(vm.auditAnimPhase).toBe('done')

    await vm.publishEmployee()
    expect(apiMock.employeePublish).toHaveBeenCalledWith('emp_1')
    expect(vm.publishState).toBe('published')

    await vm.downloadPack(false)
    expect(apiMock.employeeExportZip).toHaveBeenCalledWith(workbenchStore.target.manifest, 'emp_1', { standalone: false })
    expect(URL.createObjectURL).toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:pack')

    expect(vm.syncStepFromElapsed(1)).toBe(0)
    expect(vm.syncStepFromElapsed(21)).toBe(1)
    expect(vm.syncStepFromElapsed(30)).toBe(2)
    expect(vm.syncStepFromElapsed(129)).toBe(3)
    expect(vm.syncStepFromElapsed(159)).toBe(4)
    expect(vm.syncStepFromElapsed(189)).toBe(5)
    expect(vm.syncRoughOverallPct(420)).toBe(99)
    expect(vm.syncStepMeta(0)).toBe('')
    vm.syncState = 'running'
    vm.syncCurrentStep = 2
    vm.syncElapsedSec = 30
    expect(vm.syncStepMeta(1)).toBe('')
    expect(vm.syncStepMeta(2)).toContain('30s')
    expect(vm.syncStepMeta(3)).toBe('')
    vm.syncState = 'done'
    expect(vm.syncStepMeta(2)).toBe('')
    vm.syncState = 'error'
    vm.syncCurrentStep = 2
    expect(vm.syncStepMeta(1)).toBe('')
    expect(vm.syncStepMeta(2)).toBe('×')
    expect(vm.syncStepMeta(3)).toBe('')
    await vm.startSyncTest()
    expect(apiMock.employeeSyncTest).toHaveBeenCalledWith('emp_1', '')
    expect(vm.syncState).toBe('done')
    expect(vm.formatDiffVal(null)).toBe('(空)')
    expect(vm.formatDiffVal('x'.repeat(130))).toContain('…')
    expect(vm.formatDiffVal({ a: 1 })).toBe('{"a":1}')
  })

  it('covers right rail empty-id and error branches', async () => {
    const wrapper = mount(RightRail, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    workbenchStore.target.id = ''
    await vm.runEmployee()
    expect(vm.runResult).toContain('请先保存')
    await vm.startBenchTest()
    expect(vm.publishError).toContain('请先保存')
    await vm.startSyncTest()
    expect(vm.syncError).toContain('请先保存')

    workbenchStore.target.id = 'emp_1'
    apiMock.executeEmployeeTask.mockRejectedValueOnce(new Error('run failed'))
    await vm.runEmployee()
    expect(vm.runResult).toContain('run failed')

    apiMock.employeeBenchTest.mockResolvedValueOnce({ ok: false, error: 'bench failed' })
    await vm.startBenchTest()
    expect(vm.publishError).toContain('bench failed')

    vm.benchResult = { passed: true }
    apiMock.employeePublish.mockResolvedValueOnce({ ok: false, error: 'publish failed' })
    await vm.publishEmployee()
    expect(vm.publishError).toContain('publish failed')

    apiMock.employeeExportZip.mockResolvedValueOnce(new Blob([]))
    await vm.downloadPack(true)
    expect(vm.publishError).toContain('空包')
    apiMock.employeeExportZip.mockRejectedValueOnce(new Error('download failed'))
    await vm.downloadPack(true)
    expect(vm.publishError).toContain('download failed')

    apiMock.employeeSyncTest.mockResolvedValueOnce({ ok: false, reason: 'sync failed', stage: 'bench' })
    await vm.startSyncTest()
    expect(vm.syncError).toContain('sync failed')
    apiMock.employeeSyncTest.mockRejectedValueOnce(new Error('x'.repeat(400)))
    await vm.startSyncTest()
    expect(vm.syncError.length).toBeLessThan(330)
  })
})

describe('workbench shell coverage', () => {
  it('covers route resolution, load target normalization, switching, resizing and saving', async () => {
    vi.useFakeTimers()
    routeMock.params = { target: 'bad-kind', id: 'emp_route' }
    routeMock.query = { wfId: '44' }
    sessionStorage.setItem('modstore_employee_prefill', JSON.stringify({ identity: { id: 'emp_route', name: 'Prefill' } }))
    const wrapper = shallowMount(WorkbenchShell, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.resolveKind()).toBe('employee')
    expect(vm.resolveId()).toBe('emp_route')
    expect(workbenchStore.setTarget).toHaveBeenCalledWith('employee', 'emp_route', expect.any(Object), 'Prefill')
    expect(workbenchStore.loadEligibleWorkflows).toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(200)

    const normalized = vm.normalizeEmployeePackManifest(
      {
        id: 'legacy',
        name: 'Legacy',
        workflow_employees: [{ id: 'emp_nested', label: 'Nested', workflow_id: 7, skills: ['a'] }],
        workflow_attachment: { workflow_name: 'WF' },
      },
      'fallback',
    )
    expect(normalized.displayName).toBe('Legacy')
    expect(normalized.manifest.identity.id).toBe('legacy')
    expect(normalized.manifest.collaboration.workflow.workflow_id).toBe(7)

    await vm.buildEmptyEmployeeManifestForEditor()
    expect(apiMock.llmStatus).toHaveBeenCalled()

    vm.switchTarget('workflow')
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'workbench-shell', params: { target: 'workflow' } })

    const leftEvent = new MouseEvent('mousedown', { clientX: 100 })
    vm.onLeftResizeMouseDown(leftEvent)
    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 250 }))
    expect(vm.leftWidth).toBeGreaterThan(280)
    window.dispatchEvent(new MouseEvent('mouseup'))

    const rightEvent = new MouseEvent('mousedown', { clientX: 300 })
    vm.onRightResizeMouseDown(rightEvent)
    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 100 }))
    expect(vm.rightWidth).toBeGreaterThan(300)
    window.dispatchEvent(new MouseEvent('mouseup'))

    vm.canvasRef = { fitView: fitViewMock }
    vm.onCanvasLayoutModeChange('workflow-focus')
    expect(vm.sidePanelsCollapsed).toBe(true)
    await vi.advanceTimersByTimeAsync(120)
    expect(fitViewMock).toHaveBeenCalled()

    await vm.saveEmployee()
    expect(apiMock.employeeSaveManifest).toHaveBeenCalled()
    expect(vm.saveMsg).toContain('配置已保存')
    expect(workbenchStore.target.id).toBe('emp_saved')

    workbenchStore.target.manifest = { identity: { id: '', name: '' } }
    await vm.saveEmployee()
    expect(vm.saveMsg).toContain('请先填写')

    apiMock.employeeSaveManifest.mockResolvedValueOnce({ ok: false, error: 'save failed' })
    workbenchStore.target.manifest = baseManifest()
    await vm.saveEmployee()
    expect(vm.saveMsg).toContain('save failed')

    apiMock.employeeSaveManifest.mockRejectedValueOnce(new Error('network save failed'))
    await vm.saveEmployee()
    expect(vm.saveMsg).toContain('network save failed')

    await vm.onSelectEmployee('emp_2')
    expect(routerMock.replace).toHaveBeenCalledWith({ name: 'workbench-shell', params: { target: 'employee', id: 'emp_2' } })
  }, 15_000)

  it('covers shell API load failure, blank employee target, placeholders and embedded switching', async () => {
    apiMock.getEmployeeManifest.mockRejectedValueOnce(new Error('manifest failed'))
    routeMock.params = { target: 'employee', id: 'emp_missing' }
    const wrapper = shallowMount(WorkbenchShell, { ...globalMount, props: { embedded: true, initialTarget: 'mod' } })
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.loadError).toContain('manifest failed')

    await vm.loadTarget('employee', null)
    expect(workbenchStore.target.name).toBe('新员工')
    await vm.loadTarget('mod', 'mod_1')
    expect(workbenchStore.setTarget).toHaveBeenCalledWith('mod', 'mod_1', {}, 'mod_1')
    vm.switchTarget('skill')
    expect(workbenchStore.target.kind).toBe('skill')
  })
})
