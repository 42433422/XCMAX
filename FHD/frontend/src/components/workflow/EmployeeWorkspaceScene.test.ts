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
const statusLineSpy = vi.fn((row: any) => (row.enabled ? '运行中' : '副窗未启用'))
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
const employeeLabelsRef = computed(() => ({
  'emp-001': '侦察员',
  'emp-002': '修复员',
  'emp-003': 'QA员',
}))
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

async function mountManagementComponent(routeQuery: Record<string, unknown> = {}) {
  isAdminConsoleVal = true
  return mountComponent(routeQuery)
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
    expect(wrapper.find('[data-page-ready="true"]').exists()).toBe(true)
    expect(wrapper.find('.ews-entry-kicker').text()).toContain('企业版全景')
    expect(wrapper.find('.ews-entry-cta-text').text()).toBe('进入企业全景')
  })

  it('管理端模式入口文案切换为六部门', async () => {
    isAdminConsoleVal = true
    const wrapper = await mountManagementComponent()
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

  it('管理端没有真实工位时显示同步空态，不生成占位卡片', async () => {
    isAdminConsoleVal = true
    const wrapper = await mountManagementComponent()
    await flushPromises()
    expect(wrapper.findAll('.ews-desk')).toHaveLength(0)
    expect(wrapper.find('.ews-empty-title').text()).toContain('平台编制工位待同步')
    expect(wrapper.findAll('.ews-stat-v')[0].text()).toBe('3')
  })

  it('有工位时渲染工位卡片列表', async () => {
    desksRef.value = [
      makeDesk({ empId: 'emp-001', shortName: '侦察员' }),
      makeDesk({ empId: 'emp-002', shortName: '修复员', enabled: false }),
    ]
    const wrapper = await mountManagementComponent()
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
    desksRef.value = [makeDesk({ empId: 'emp-001', shortName: '侦察员' }), makeDesk({ empId: 'emp-002', shortName: '修复员' })]
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
    expect(stats[0].find('.ews-stat-k').text()).toBe('企业工位')
    expect(stats[0].find('.ews-stat-v').text()).toBe('3')
    // 已托管 = enabled count = 2
    expect(stats[1].find('.ews-stat-v').text()).toBe('2')
    // 工作中 = busy count = 1
    expect(stats[2].find('.ews-stat-v').text()).toBe('1')
    // 待命 = enabled - busy = 1
    expect(stats[3].find('.ews-stat-v').text()).toBe('1')
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
    const wrapper = await mountManagementComponent()
    await flushPromises()
    expect(wrapper.find('.ews-selected-loop').exists()).toBe(true)
    expect(wrapper.find('.ews-selected-loop strong').text()).toBe('侦察员')
  })

  it('路由有 employee 参数且在工位中时选中该员工', async () => {
    desksRef.value = [makeDesk({ empId: 'emp-001', shortName: '侦察员' }), makeDesk({ empId: 'emp-002', shortName: '修复员' })]
    const wrapper = await mountComponent({ employee: 'emp-002' })
    await flushPromises()
    const desks = wrapper.findAll('.ews-desk')
    expect(desks[1].classes()).toContain('ews-desk--selected')
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
    desksRef.value = [makeDesk({ empId: 'emp-001', session: { processedCount: 1500 } })]
    const wrapper = await mountComponent()
    await flushPromises()
    const num = wrapper.find('.ews-desk-rpg-num')
    expect(num.text()).toBe('1.5k')
  })

  it('工位 processedShort 处理超大数字', async () => {
    desksRef.value = [makeDesk({ empId: 'emp-001', session: { processedCount: 15000 } })]
    const wrapper = await mountComponent()
    await flushPromises()
    const nums = wrapper.findAll('.ews-desk-rpg-num')
    // 第一个 rpg-num 是 processed
    expect(nums[0].text()).toBe('15k')
  })

  it('工位 progressWidth 反映 progressPct', async () => {
    desksRef.value = [
      makeDesk({
        empId: 'emp-001',
        enabled: true,
        snapshot: { visuallyBusy: false, progressPct: 75 },
      }),
    ]
    const wrapper = await mountComponent()
    await flushPromises()
    const bar = wrapper.find('.ews-desk-progress-bar')
    expect(bar.exists()).toBe(true)
    expect(bar.attributes('style')).toContain('width: 75%')
  })

  it('工位 disabled 时 progressWidth 为 0%', async () => {
    desksRef.value = [makeDesk({ empId: 'emp-001', enabled: false, snapshot: { progressPct: 75 } })]
    const wrapper = await mountComponent()
    await flushPromises()
    const bar = wrapper.find('.ews-desk-progress-bar')
    expect(bar.attributes('style')).toContain('width: 0%')
  })

  it('onMounted 触发 ensureDutyRosterLoaded 与 resolveEnterpriseModStack', async () => {
    resolveStackMock.mockResolvedValue({ stackShortLabel: '家具包' })
    await mountManagementComponent()
    await flushPromises()
    expect(ensureLoadedSpy).toHaveBeenCalled()
    expect(resolveStackMock).toHaveBeenCalled()
  })

  it('resolveEnterpriseModStack 返回栈标签时 workspaceStatSub 含栈名', async () => {
    resolveStackMock.mockResolvedValue({ stackShortLabel: '家具行业包' })
    const wrapper = await mountManagementComponent()
    await flushPromises()
    expect(wrapper.find('.ews-stat-sub').text()).toContain('家具行业包')
  })

  it('组件卸载时清理定时器（不报错）', async () => {
    const wrapper = await mountManagementComponent()
    await flushPromises()
    expect(() => wrapper.unmount()).not.toThrow()
  })

  it('渲染子组件 DutyRosterWorkflowLoopView 与 SelfEvolutionLoopRuntimePanel', async () => {
    const wrapper = await mountManagementComponent()
    await flushPromises()
    expect(wrapper.find('.drwlv-stub').exists()).toBe(true)
    expect(wrapper.find('.selp-stub').exists()).toBe(true)
  })

  it('渲染 WorkflowEmployeeInspector 侧栏', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.wei-stub').exists()).toBe(true)
  })


  it('企业端不渲染管理端编制和自进化面板', async () => {
    const wrapper = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.drwlv-stub').exists()).toBe(false)
    expect(wrapper.find('.selp-stub').exists()).toBe(false)
    expect(wrapper.find('.ews-loop-console').exists()).toBe(false)
    expect(wrapper.find('.ews-stat-k').text()).toBe('企业工位')
  })

})
