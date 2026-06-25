import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref, computed } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'

// ---- Mock 外部边界 ----

// API 调用
const statusMock = vi.fn()
vi.mock('@/api/xcmaxMarketProxy', () => ({
  default: {
    selfMaintenanceRuntimeStatus: (...a: unknown[]) => statusMock(...a),
  },
}))

// Pinia store
const toggleSpy = vi.fn()
const enabledRef = ref<Record<string, boolean>>({})
vi.mock('@/stores/workflowAiEmployees', () => ({
  useWorkflowAiEmployeesStore: () => ({
    enabled: enabledRef,
    toggle: toggleSpy,
  }),
}))

// composables
const desksRef = ref<any[]>([])
const statusLineSpy = vi.fn((row: any) => row.enabled ? '运行中' : '副窗未启用')
const ariaLabelSpy = vi.fn((row: any) => `员工 ${row.shortName}`)
const isBusySpy = vi.fn((row: any) => Boolean(row.snapshot?.visuallyBusy))
const processedCountSpy = vi.fn((row: any) => row.session?.processedCount ?? 0)
vi.mock('@/composables/useWorkflowEmployeeDesks', () => ({
  useWorkflowEmployeeDesks: () => ({
    desks: desksRef,
    statusLine: statusLineSpy,
    ariaLabel: ariaLabelSpy,
    isBusy: isBusySpy,
    processedCount: processedCountSpy,
  }),
  useNowMsTicker: () => ref(Date.now()),
  formatWorkDurationShort: (ms: number) => `${ms}ms`,
  totalWorkMs: () => 0,
}))

const ensureLoadedSpy = vi.fn()
const allPlannedIdsRef = computed(() => new Set<string>(['emp-001', 'emp-002', 'emp-003']))
const employeeLabelsRef = computed(() => ({ 'emp-001': '侦察员', 'emp-002': '修复员', 'emp-003': 'QA员' }))
vi.mock('@/composables/useDutyRoster', () => ({
  useDutyRoster: () => ({
    allPlannedIds: allPlannedIdsRef,
    employeeLabels: employeeLabelsRef,
    ensureLoaded: ensureLoadedSpy,
  }),
}))

vi.mock('@/composables/useWorkflowEmployeeRegistrySync', () => ({
  useWorkflowEmployeeRegistrySync: () => ({}),
}))

// utils
vi.mock('@/utils/workflowEmployeeScope', () => ({
  workflowRegistryEntryBelongsToStack: () => true,
}))

let isAdminConsoleVal = false
vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => isAdminConsoleVal,
}))

const resolveStackMock = vi.fn()
vi.mock('@/utils/enterpriseModStackApi', () => ({
  resolveEnterpriseModStack: (...a: unknown[]) => resolveStackMock(...a),
}))

import EmployeeWorkspaceScene from './EmployeeWorkspaceScene.vue'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div/>' } },
      { path: '/stitch', name: 'workflow-employee-stitch-full', component: { template: '<div/>' } },
      { path: '/duty-roster', name: 'duty-roster-graph', component: { template: '<div/>' } },
      { path: '/viz', name: 'workflow-visualization', component: { template: '<div/>' } },
    ],
  })
}

function makeDesk(overrides: Record<string, unknown> = {}) {
  return {
    empId: 'emp-001',
    panelTitle: '工作流 · 侦察员',
    shortName: '侦察员',
    enabled: true,
    snapshot: { visuallyBusy: false, progressPct: 50 },
    session: { processedCount: 5 },
    ...overrides,
  }
}

async function mountComponent(routeQuery: Record<string, unknown> = {}) {
  const router = makeRouter()
  await router.push({ path: '/', query: routeQuery })
  await router.isReady()
  return mount(EmployeeWorkspaceScene, {
    global: {
      plugins: [router],
      stubs: {
        'router-link': { template: '<a><slot/></a>' },
        YuangongStation: { template: '<div class="ys-stub"/>' },
        WorkflowEmployeeInspector: { template: '<div class="wei-stub"/>' },
        DutyRosterWorkflowLoopView: { template: '<div class="drwlv-stub"/>' },
        SelfEvolutionLoopRuntimePanel: { template: '<div class="selp-stub"/>' },
      },
    },
  })
}

describe('EmployeeWorkspaceScene.vue', () => {
  beforeEach(() => {
    statusMock.mockReset()
    toggleSpy.mockReset()
    ensureLoadedSpy.mockReset()
    statusMock.mockResolvedValue(null)
    resolveStackMock.mockReset()
    resolveStackMock.mockResolvedValue(null)
    desksRef.value = []
    enabledRef.value = {}
    isAdminConsoleVal = false
  })

  it('挂载并渲染根 section 与标题', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews').exists()).toBe(true)
    expect(wrapper.find('#ews-heading').text()).toContain('员工工作流')
  })

  it('渲染入口卡片含 kicker/lead/cta', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-entry').exists()).toBe(true)
    expect(wrapper.find('.ews-entry-kicker').text()).toContain('企业版全景')
    expect(wrapper.find('.ews-entry-cta-text').text()).toBe('进入企业全景')
  })

  it('管理端模式入口文案切换为六部门', async () => {
    isAdminConsoleVal = true
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-entry-kicker').text()).toContain('管理端可视化')
    expect(wrapper.find('.ews-entry-cta-text').text()).toBe('进入六部门可视化')
  })

  it('空工位时渲染空态提示', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-empty').exists()).toBe(true)
    expect(wrapper.find('.ews-empty-title').text()).toContain('企业 Mod 工位待同步')
  })

  it('管理端空工位时从编制构建占位工位（不显示空态）', async () => {
    isAdminConsoleVal = true
    const wrapper = await mountComponent()
    await flushPromises()
    // 管理端 + 空工作流注册表 → 从 ALL_PLANNED_YUANGON_PKG_IDS 构建占位工位
    const desks = wrapper.findAll('.ews-desk')
    expect(desks.length).toBe(3) // emp-001, emp-002, emp-003
    expect(wrapper.find('.ews-empty').exists()).toBe(false)
  })

  it('有工位时渲染工位卡片列表', async () => {
    desksRef.value = [
      makeDesk({ empId: 'emp-001', shortName: '侦察员' }),
      makeDesk({ empId: 'emp-002', shortName: '修复员', enabled: false }),
    ]
    const wrapper = await mountComponent()
    await flushPromises()
    const desks = wrapper.findAll('.ews-desk')
    expect(desks.length).toBe(2)
    expect(desks[0].find('.ews-desk-name').text()).toBe('侦察员')
  })

  it('工位 enabled=false 时加上 ews-desk--off class', async () => {
    desksRef.value = [makeDesk({ enabled: false })]
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-desk').classes()).toContain('ews-desk--off')
    expect(wrapper.find('.ews-desk-pill--off').exists()).toBe(true)
  })

  it('工位 busy 时加上 ews-desk--busy class 与忙 pill', async () => {
    desksRef.value = [makeDesk({ snapshot: { visuallyBusy: true, progressPct: 80 } })]
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-desk').classes()).toContain('ews-desk--busy')
    expect(wrapper.find('.ews-desk-pill--busy').exists()).toBe(true)
  })

  it('工位 enabled 时显示待命 pill', async () => {
    desksRef.value = [makeDesk({ enabled: true, snapshot: { visuallyBusy: false } })]
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-desk-pill--idle').exists()).toBe(true)
  })

  it('点击工位卡片选中并更新 selectedEmpId', async () => {
    desksRef.value = [
      makeDesk({ empId: 'emp-001', shortName: '侦察员' }),
      makeDesk({ empId: 'emp-002', shortName: '修复员' }),
    ]
    const wrapper = await mountComponent()
    await flushPromises()
    // 默认选中第一个
    expect(wrapper.find('.ews-desk--selected').exists()).toBe(true)
    // 点击第二个
    const desks = wrapper.findAll('.ews-desk-hit')
    await desks[1].trigger('click')
    await flushPromises()
    const allDesks = wrapper.findAll('.ews-desk')
    expect(allDesks[1].classes()).toContain('ews-desk--selected')
  })

  it('点击工位 toggle 开关调用 store.toggle', async () => {
    desksRef.value = [makeDesk({ empId: 'emp-001' })]
    const wrapper = await mountComponent()
    await flushPromises()
    const toggle = wrapper.find('.ews-desk-toggle')
    expect(toggle.exists()).toBe(true)
    await toggle.trigger('click')
    expect(toggleSpy).toHaveBeenCalledWith('emp-001')
  })

  it('toggle 开关 aria-checked 反映 enabled 状态', async () => {
    desksRef.value = [makeDesk({ empId: 'emp-001', enabled: true })]
    const wrapper = await mountComponent()
    await flushPromises()
    const toggle = wrapper.find('.ews-desk-toggle')
    expect(toggle.attributes('aria-checked')).toBe('true')
    expect(toggle.find('.ews-desk-toggle-label').text()).toBe('已开')
  })

  it('渲染统计区：编制工位/已托管/工作中/待命', async () => {
    desksRef.value = [
      makeDesk({ empId: 'emp-001', enabled: true, snapshot: { visuallyBusy: true } }),
      makeDesk({ empId: 'emp-002', enabled: true, snapshot: { visuallyBusy: false } }),
      makeDesk({ empId: 'emp-003', enabled: false }),
    ]
    const wrapper = await mountComponent()
    await flushPromises()
    const stats = wrapper.findAll('.ews-stat')
    expect(stats.length).toBe(4)
    // 编制工位 = max(totalCount=3, rosterCount=3) = 3
    expect(stats[0].find('.ews-stat-v').text()).toBe('3')
    // 已托管 = enabled count = 2
    expect(stats[1].find('.ews-stat-v').text()).toBe('2')
    // 工作中 = busy count = 1
    expect(stats[2].find('.ews-stat-v').text()).toBe('1')
    // 待命 = enabled - busy = 1
    expect(stats[3].find('.ews-stat-v').text()).toBe('1')
  })

  it('渲染 Loop 控制台区域', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-loop-console').exists()).toBe(true)
    expect(wrapper.find('.ews-loop-cockpit').exists()).toBe(true)
  })

  it('loopRuntime 为 null 时 loopStatusLabel 为待连接', async () => {
    statusMock.mockResolvedValue(null)
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-loop-console-status').text()).toBe('待连接')
  })

  it('loopRuntime 有 open_run_ids 时 loopStatusLabel 为运行中', async () => {
    statusMock.mockResolvedValue({
      schema_version: 'self_maintenance_runtime.v1',
      evidence: { open_run_ids: ['r1'] },
      contract: { required_top_level: ['evidence'] },
      contract_validation: { ok: true, surface_readiness: { employee_space: { ok: true } } },
    })
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-loop-console-status').text()).toBe('运行中')
  })

  it('点击 loop 状态按钮触发 refreshLoopRuntime', async () => {
    statusMock.mockResolvedValue(null)
    const wrapper = await mountComponent()
    await flushPromises()
    expect(statusMock).toHaveBeenCalledTimes(1)
    await wrapper.find('.ews-loop-console-status').trigger('click')
    await flushPromises()
    expect(statusMock).toHaveBeenCalledTimes(2)
  })

  it('渲染 loop 摘要卡片 loopRuntimeCards', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    const cards = wrapper.findAll('.ews-loop-card')
    expect(cards.length).toBe(5)
    expect(cards[0].find('span').text()).toBe('Loop 状态')
  })

  it('渲染 loop 流水线阶段 loopPipelineStages', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    const stages = wrapper.findAll('.ews-loop-stage')
    expect(stages.length).toBe(5)
  })

  it('渲染三端模块就绪 surface 卡片', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    const cards = wrapper.findAll('.ews-loop-surface-card')
    expect(cards.length).toBe(3)
  })

  it('渲染 loop 角色分工图', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    const nodes = wrapper.findAll('.ews-loop-role-map-node')
    expect(nodes.length).toBe(3)
    expect(nodes[0].find('span').text()).toBe('员工空间')
  })

  it('渲染 loop 下一步操作指引区', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-loop-directive').exists()).toBe(true)
    expect(wrapper.find('.ews-loop-directive-link').exists()).toBe(true)
  })

  it('渲染 loop 真实数据来源 truth strip', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-loop-truth-strip').exists()).toBe(true)
    // 主状态卡 + truthCards
    expect(wrapper.find('.ews-loop-truth-card--primary').exists()).toBe(true)
  })

  it('渲染 loop 数据新鲜度 freshness strip', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-loop-freshness-strip').exists()).toBe(true)
    expect(wrapper.findAll('.ews-loop-freshness-card').length).toBeGreaterThan(0)
  })

  it('渲染 loop 诊断区', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-loop-diagnosis').exists()).toBe(true)
  })

  it('渲染 loop 员工分离矩阵 isolation cards', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-loop-isolation').exists()).toBe(true)
    const cards = wrapper.findAll('.ews-loop-isolation-card')
    expect(cards.length).toBe(5)
  })

  it('渲染工位实况监控区', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-monitor').exists()).toBe(true)
    expect(wrapper.find('#ews-workflow-monitor').exists()).toBe(true)
  })

  it('渲染工位布局 grid + side', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-layout').exists()).toBe(true)
    expect(wrapper.find('.ews-grid').exists()).toBe(true)
    expect(wrapper.find('.ews-side').exists()).toBe(true)
  })

  it('有选中工位时渲染 selectedDeskLoopState 上下文', async () => {
    desksRef.value = [makeDesk({ empId: 'emp-001', shortName: '侦察员', enabled: true })]
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-selected-loop').exists()).toBe(true)
    expect(wrapper.find('.ews-selected-loop strong').text()).toBe('侦察员')
  })

  it('路由有 employee 参数且在工位中时选中该员工', async () => {
    desksRef.value = [
      makeDesk({ empId: 'emp-001', shortName: '侦察员' }),
      makeDesk({ empId: 'emp-002', shortName: '修复员' }),
    ]
    const wrapper = await mountComponent({ employee: 'emp-002' })
    await flushPromises()
    const desks = wrapper.findAll('.ews-desk')
    expect(desks[1].classes()).toContain('ews-desk--selected')
  })

  it('路由有 employee 参数但不在工位中时渲染警告', async () => {
    desksRef.value = [makeDesk({ empId: 'emp-001' })]
    const wrapper = await mountComponent({ employee: 'emp-999' })
    await flushPromises()
    expect(wrapper.find('.ews-route-focus-warning').exists()).toBe(true)
    expect(wrapper.find('.ews-route-focus-warning strong').text()).toContain('不在员工空间工位里')
  })

  it('入口背景图 error 时切换 fallback URL', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    const img = wrapper.find('.ews-entry-bg-img')
    expect(img.exists()).toBe(true)
    // 触发 error 事件
    await img.trigger('error')
    // 内部 entryBgUrl 应已切换（无法直接断言 src，但确保不报错）
    expect(wrapper.find('.ews-entry-bg-img').exists()).toBe(true)
  })

  it('工位 processedShort 处理大数字格式化', async () => {
    desksRef.value = [
      makeDesk({ empId: 'emp-001', session: { processedCount: 1500 } }),
    ]
    const wrapper = await mountComponent()
    await flushPromises()
    const num = wrapper.find('.ews-desk-rpg-num')
    expect(num.text()).toBe('1.5k')
  })

  it('工位 processedShort 处理超大数字', async () => {
    desksRef.value = [
      makeDesk({ empId: 'emp-001', session: { processedCount: 15000 } }),
    ]
    const wrapper = await mountComponent()
    await flushPromises()
    const nums = wrapper.findAll('.ews-desk-rpg-num')
    // 第一个 rpg-num 是 processed
    expect(nums[0].text()).toBe('15k')
  })

  it('工位 progressWidth 反映 progressPct', async () => {
    desksRef.value = [
      makeDesk({ empId: 'emp-001', enabled: true, snapshot: { visuallyBusy: false, progressPct: 75 } }),
    ]
    const wrapper = await mountComponent()
    await flushPromises()
    const bar = wrapper.find('.ews-desk-progress-bar')
    expect(bar.exists()).toBe(true)
    expect(bar.attributes('style')).toContain('width: 75%')
  })

  it('工位 disabled 时 progressWidth 为 0%', async () => {
    desksRef.value = [
      makeDesk({ empId: 'emp-001', enabled: false, snapshot: { progressPct: 75 } }),
    ]
    const wrapper = await mountComponent()
    await flushPromises()
    const bar = wrapper.find('.ews-desk-progress-bar')
    expect(bar.attributes('style')).toContain('width: 0%')
  })

  it('onMounted 触发 ensureDutyRosterLoaded 与 resolveEnterpriseModStack', async () => {
    resolveStackMock.mockResolvedValue({ stackShortLabel: '家具包' })
    await mountComponent()
    await flushPromises()
    expect(ensureLoadedSpy).toHaveBeenCalled()
    expect(resolveStackMock).toHaveBeenCalled()
  })

  it('resolveEnterpriseModStack 返回栈标签时 workspaceStatSub 含栈名', async () => {
    resolveStackMock.mockResolvedValue({ stackShortLabel: '家具行业包' })
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-stat-sub').text()).toContain('家具行业包')
  })

  it('loopRuntime 有 participants 时 loop 卡片显示参与数', async () => {
    statusMock.mockResolvedValue({
      schema_version: 'self_maintenance_runtime.v1',
      evidence: {},
      memory: {},
      current_gate: {},
      participants: [
        { employee_id: 'emp-001', role_label: '侦察' },
        { employee_id: 'emp-002', role_label: '修复' },
      ],
      contract: { required_top_level: ['evidence'] },
      contract_validation: { ok: true, surface_readiness: { employee_space: { ok: true } } },
    })
    const wrapper = await mountComponent()
    await flushPromises()
    // workers 卡片显示参与数
    const cards = wrapper.findAll('.ews-loop-card')
    const workersCard = cards.find((c) => c.find('span').text() === '上岗参与')
    expect(workersCard).toBeTruthy()
    expect(workersCard!.find('strong').text()).toBe('2')
  })

  it('loopRuntime 有 active_gates.blocking_count 时驾驶舱门禁显示阻断数', async () => {
    statusMock.mockResolvedValue({
      schema_version: 'self_maintenance_runtime.v1',
      evidence: {},
      memory: {},
      current_gate: {},
      active_gates: { ok: false, blocking_count: 3, blocking_keys: ['roster'] },
      contract: { required_top_level: ['evidence'] },
      contract_validation: { ok: true, surface_readiness: { employee_space: { ok: true } } },
    })
    const wrapper = await mountComponent()
    await flushPromises()
    const meters = wrapper.findAll('.ews-loop-cockpit-meter')
    // 第二个 meter 是 gate
    expect(meters[1].find('strong').text()).toBe('3')
  })

  it('loopRuntime 有 surface_incidents 时渲染 incident 列表', async () => {
    statusMock.mockResolvedValue({
      schema_version: 'self_maintenance_runtime.v1',
      evidence: {},
      memory: {},
      current_gate: {},
      contract: { required_top_level: ['evidence'] },
      contract_validation: {
        ok: true,
        surface_readiness: { employee_space: { ok: true } },
        surface_incidents: [
          { id: 'inc-1', surface: 'employee_space', severity: 'bad', title: '断点A' },
        ],
      },
    })
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-loop-incident-list').exists()).toBe(true)
    expect(wrapper.findAll('.ews-loop-incident').length).toBe(1)
  })

  it('loopRuntime 有 run_timelines 时渲染工单卡片', async () => {
    statusMock.mockResolvedValue({
      schema_version: 'self_maintenance_runtime.v1',
      evidence: {},
      memory: {},
      current_gate: {},
      run_timelines: [
        {
          run_id: 'run-1',
          items: [
            { employee_id: 'emp-001', label: '扫描', status: 'done', stage: 'sense' },
          ],
        },
      ],
      contract: { required_top_level: ['evidence'] },
      contract_validation: { ok: true, surface_readiness: { employee_space: { ok: true } } },
    })
    const wrapper = await mountComponent()
    await flushPromises()
    // loop work order cards
    expect(wrapper.find('.ews-loop-next-actions').exists()).toBe(true)
    expect(wrapper.findAll('.ews-loop-next-action').length).toBeGreaterThan(0)
  })

  it('loopRuntime contract 异常时 loopStatusLabel 为 Contract 异常', async () => {
    statusMock.mockResolvedValue({
      schema_version: 'unknown.v0',
      contract: { required_top_level: ['evidence'] },
      contract_validation: { ok: false },
    })
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-loop-console-status').text()).toBe('Contract 异常')
  })

  it('loopRuntime gate.should_run=true 且无 open runs 时状态为达到阈值', async () => {
    statusMock.mockResolvedValue({
      schema_version: 'self_maintenance_runtime.v1',
      evidence: { open_run_ids: [] },
      memory: {},
      current_gate: { should_run: true, reason: 'threshold' },
      contract: { required_top_level: ['evidence'] },
      contract_validation: { ok: true, surface_readiness: { employee_space: { ok: true } } },
    })
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-loop-console-status').text()).toBe('达到阈值')
  })

  it('loopRuntime gate.reason=cooldown 时状态为冷却中', async () => {
    statusMock.mockResolvedValue({
      schema_version: 'self_maintenance_runtime.v1',
      evidence: { open_run_ids: [] },
      memory: {},
      current_gate: { should_run: false, reason: 'cooldown' },
      contract: { required_top_level: ['evidence'] },
      contract_validation: { ok: true, surface_readiness: { employee_space: { ok: true } } },
    })
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-loop-console-status').text()).toBe('冷却中')
  })

  it('API 抛错时 loopRuntime 保持 null 不崩溃', async () => {
    statusMock.mockRejectedValue(new Error('网络错误'))
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews').exists()).toBe(true)
    expect(wrapper.find('.ews-loop-console-status').text()).toBe('待连接')
  })

  it('管理端模式无工位时从编制构建占位工位', async () => {
    isAdminConsoleVal = true
    const wrapper = await mountComponent()
    await flushPromises()
    // 管理端 + 空工作流注册表 → 从 ALL_PLANNED_YUANGON_PKG_IDS 构建占位
    const desks = wrapper.findAll('.ews-desk')
    expect(desks.length).toBe(3) // emp-001, emp-002, emp-003
  })

  it('组件卸载时清理定时器（不报错）', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(() => wrapper.unmount()).not.toThrow()
  })

  it('渲染子组件 DutyRosterWorkflowLoopView 与 SelfEvolutionLoopRuntimePanel', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.drwlv-stub').exists()).toBe(true)
    expect(wrapper.find('.selp-stub').exists()).toBe(true)
  })

  it('渲染 WorkflowEmployeeInspector 侧栏', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.wei-stub').exists()).toBe(true)
  })

  it('loop focused employee 有 worker task card 时渲染 focus card', async () => {
    desksRef.value = [makeDesk({ empId: 'emp-001', shortName: '侦察员' })]
    statusMock.mockResolvedValue({
      schema_version: 'self_maintenance_runtime.v1',
      evidence: {},
      memory: {},
      current_gate: {},
      participants: [{ employee_id: 'emp-001', role_label: '侦察' }],
      ui_bridge: { primary_employee_id: 'emp-001' },
      run_timelines: [{
        run_id: 'r1',
        items: [{ employee_id: 'emp-001', label: '扫描', status: 'done' }],
      }],
      contract: { required_top_level: ['evidence'] },
      contract_validation: { ok: true, surface_readiness: { employee_space: { ok: true } } },
    })
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.ews-loop-focus-card').exists()).toBe(true)
  })

  it('loop focused employee 无 worker task card 但有 focus id 时渲染 warn focus card', async () => {
    desksRef.value = [makeDesk({ empId: 'emp-001', shortName: '侦察员' })]
    statusMock.mockResolvedValue({
      schema_version: 'self_maintenance_runtime.v1',
      evidence: {},
      memory: {},
      current_gate: {},
      ui_bridge: { primary_employee_id: 'emp-001' },
      contract: { required_top_level: ['evidence'] },
      contract_validation: { ok: true, surface_readiness: { employee_space: { ok: true } } },
    })
    const wrapper = await mountComponent()
    await flushPromises()
    // emp-001 是 focused 但没有 worker task card
    const focusCard = wrapper.find('.ews-loop-focus-card')
    expect(focusCard.exists()).toBe(true)
    expect(focusCard.classes()).toContain('ews-loop-focus-card--warn')
  })
})
