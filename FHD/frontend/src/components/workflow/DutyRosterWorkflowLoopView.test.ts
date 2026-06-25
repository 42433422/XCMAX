import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'

const allPlannedIdsRef = ref<string[]>(['e1', 'e2'])
const employeeLabelsRef = ref<Record<string, string>>({ e1: '员工1', e2: '员工2' })
const employeeDescriptionsRef = ref<Record<string, string>>({ e1: '描述1', e2: '描述2' })
const ensureLoadedMock = vi.fn()

vi.mock('@/composables/useDutyRoster', () => ({
  useDutyRoster: () => ({
    allPlannedIds: allPlannedIdsRef,
    employeeLabels: employeeLabelsRef,
    employeeDescriptions: employeeDescriptionsRef,
    ensureLoaded: ensureLoadedMock,
  }),
}))

const statusRef = ref({
  ok: true,
  source: 'api',
  plannedCount: 2,
  catalogRegisteredCount: 2,
  localInstalledCount: 2,
  missingCatalogIds: [],
  missingLocalIds: [],
  extraIds: [],
  missingCatalogCount: 0,
  missingLocalCount: 0,
  extraCount: 0,
  schedulerJobCount: 0,
  schedulerRunning: null,
  checkedAt: null,
  message: '',
})
const loadingRef = ref(false)
const readyRef = ref(true)
const healthLabelRef = ref('健康')
const detailLineRef = ref('详情')
const refreshMock = vi.fn().mockResolvedValue(undefined)

vi.mock('@/composables/useDutyRosterLoopStatus', () => ({
  useDutyRosterLoopStatus: () => ({
    status: statusRef,
    loading: loadingRef,
    ready: readyRef,
    healthLabel: healthLabelRef,
    detailLine: detailLineRef,
    refresh: refreshMock,
  }),
}))

vi.mock('@/domain/yuangonDutyRoster', async () => {
  const actual = await vi.importActual<typeof import('@/domain/yuangonDutyRoster')>(
    '@/domain/yuangonDutyRoster',
  )
  return { ...actual }
})

import DutyRosterWorkflowLoopView from './DutyRosterWorkflowLoopView.vue'

function mountView(props: Record<string, unknown> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      {
        path: '/duty-roster-graph',
        name: 'duty-roster-graph',
        component: { template: '<div />' },
      },
      {
        path: '/workflow-employee-space',
        name: 'workflow-employee-space',
        component: { template: '<div />' },
      },
      {
        path: '/workflow-visualization',
        name: 'workflow-visualization',
        component: { template: '<div />' },
      },
    ],
  })
  return router.push('/').then(() =>
    router.isReady().then(() =>
      mount(DutyRosterWorkflowLoopView, {
        props,
        global: {
          plugins: [router],
          stubs: { RouterLink: { template: '<a><slot /></a>' } },
        },
      }),
    ),
  )
}

describe('DutyRosterWorkflowLoopView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    allPlannedIdsRef.value = ['e1', 'e2']
    employeeLabelsRef.value = { e1: '员工1', e2: '员工2' }
    employeeDescriptionsRef.value = { e1: '描述1', e2: '描述2' }
    statusRef.value = {
      ok: true,
      source: 'api',
      plannedCount: 2,
      catalogRegisteredCount: 2,
      localInstalledCount: 2,
      missingCatalogIds: [],
      missingLocalIds: [],
      extraIds: [],
      missingCatalogCount: 0,
      missingLocalCount: 0,
      extraCount: 0,
      schedulerJobCount: 0,
      schedulerRunning: null,
      checkedAt: null,
      message: '',
    }
    loadingRef.value = false
    readyRef.value = true
    healthLabelRef.value = '健康'
    detailLineRef.value = '详情'
    refreshMock.mockResolvedValue(undefined)
  })

  it('renders the section container', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.drlv').exists()).toBe(true)
  })

  it('renders the title', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.drlv-title').text()).toContain('编制 → 员工空间')
  })

  it('renders the kicker text', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.drlv-kicker').text()).toBe('编制驱动流程')
  })

  it('renders detail line from composable', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.drlv-desc').text()).toBe('详情')
  })

  it('renders refresh button', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.drlv-refresh').exists()).toBe(true)
    expect(wrapper.find('.drlv-refresh').text()).toBe('刷新')
  })

  it('shows "刷新中" text and disables button when loading', async () => {
    loadingRef.value = true
    const wrapper = await mountView()
    expect(wrapper.find('.drlv-refresh').text()).toBe('刷新中')
    expect(wrapper.find('.drlv-refresh').attributes('disabled')).toBeDefined()
  })

  it('calls refresh when refresh button is clicked', async () => {
    const wrapper = await mountView()
    await wrapper.find('.drlv-refresh').trigger('click')
    expect(refreshMock).toHaveBeenCalled()
  })

  it('renders 4 health cards', async () => {
    const wrapper = await mountView()
    expect(wrapper.findAll('.drlv-health-card')).toHaveLength(4)
  })

  it('renders planned count in health card', async () => {
    const wrapper = await mountView()
    const cards = wrapper.findAll('.drlv-health-card')
    expect(cards[0].find('.drlv-health-value').text()).toBe('2')
  })

  it('renders local installed count in health card', async () => {
    const wrapper = await mountView()
    const cards = wrapper.findAll('.drlv-health-card')
    expect(cards[1].find('.drlv-health-value').text()).toBe('2/2')
  })

  it('renders catalog count in health card', async () => {
    const wrapper = await mountView()
    const cards = wrapper.findAll('.drlv-health-card')
    expect(cards[2].find('.drlv-health-value').text()).toBe('2/2')
  })

  it('renders gap count in health card', async () => {
    const wrapper = await mountView()
    const cards = wrapper.findAll('.drlv-health-card')
    expect(cards[3].find('.drlv-health-value').text()).toBe('0')
  })

  it('renders 4 loop nodes', async () => {
    const wrapper = await mountView()
    expect(wrapper.findAll('.drlv-node')).toHaveLength(4)
  })

  it('renders loop node titles', async () => {
    const wrapper = await mountView()
    const titles = wrapper.findAll('.drlv-node-title').map((n) => n.text())
    expect(titles).toContain('编制图谱')
    expect(titles).toContain('员工空间')
    expect(titles).toContain('流程可视化')
    expect(titles).toContain('执行回写')
  })

  it('renders status section with ok class when ready', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.drlv-status').classes()).toContain('drlv-status--ok')
  })

  it('renders status section with warn class when not ready', async () => {
    readyRef.value = false
    const wrapper = await mountView()
    expect(wrapper.find('.drlv-status').classes()).toContain('drlv-status--warn')
  })

  it('renders health label in status section', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.drlv-status strong').text()).toBe('健康')
  })

  it('renders ready risk line when ready', async () => {
    const wrapper = await mountView()
    const spans = wrapper.findAll('.drlv-status span')
    const riskSpan = spans[spans.length - 1]
    expect(riskSpan.text()).toContain('已对齐')
  })

  it('renders risk line with missing local count when not ready', async () => {
    readyRef.value = false
    statusRef.value.missingLocalCount = 3
    const wrapper = await mountView()
    const spans = wrapper.findAll('.drlv-status span')
    const riskSpan = spans[spans.length - 1]
    expect(riskSpan.text()).toContain('本机缺包 3')
  })

  it('renders risk line with missing catalog count when not ready', async () => {
    readyRef.value = false
    statusRef.value.missingCatalogCount = 1
    const wrapper = await mountView()
    const spans = wrapper.findAll('.drlv-status span')
    const riskSpan = spans[spans.length - 1]
    expect(riskSpan.text()).toContain('Catalog 缺岗 1')
  })

  it('renders risk line with extra count when not ready', async () => {
    readyRef.value = false
    statusRef.value.extraCount = 2
    const wrapper = await mountView()
    const spans = wrapper.findAll('.drlv-status span')
    const riskSpan = spans[spans.length - 1]
    expect(riskSpan.text()).toContain('编制外 2')
  })

  it('renders departments section', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.drlv-depts').exists()).toBe(true)
  })

  it('renders employee section when surface is workflow-visualization and not compact', async () => {
    const wrapper = await mountView({ surface: 'workflow-visualization', compact: false })
    expect(wrapper.find('.drlv-employees').exists()).toBe(true)
  })

  it('hides employee section when compact is true', async () => {
    const wrapper = await mountView({ surface: 'workflow-visualization', compact: true })
    expect(wrapper.find('.drlv-employees').exists()).toBe(false)
  })

  it('hides employee section when surface is employee-space', async () => {
    const wrapper = await mountView({ surface: 'employee-space', compact: false })
    expect(wrapper.find('.drlv-employees').exists()).toBe(false)
  })

  it('renders employee cards for planned employees', async () => {
    const wrapper = await mountView({ surface: 'workflow-visualization', compact: false })
    expect(wrapper.findAll('.drlv-employee').length).toBeGreaterThanOrEqual(1)
  })

  it('renders employee count in header', async () => {
    const wrapper = await mountView({ surface: 'workflow-visualization', compact: false })
    expect(wrapper.find('.drlv-employees-count').text()).toContain('员工')
  })

  it('renders employee name from labels', async () => {
    const wrapper = await mountView({ surface: 'workflow-visualization', compact: false })
    expect(wrapper.text()).toContain('员工1')
    expect(wrapper.text()).toContain('员工2')
  })

  it('renders employee description', async () => {
    const wrapper = await mountView({ surface: 'workflow-visualization', compact: false })
    expect(wrapper.text()).toContain('描述1')
  })

  it('marks employee as ok status when not missing', async () => {
    const wrapper = await mountView({ surface: 'workflow-visualization', compact: false })
    const status = wrapper.find('.drlv-employee-status')
    expect(status.classes()).toContain('drlv-employee-status--ok')
    expect(status.text()).toBe('已对齐')
  })

  it('marks employee as warn when missing locally', async () => {
    statusRef.value.missingLocalIds = ['e1']
    const wrapper = await mountView({ surface: 'workflow-visualization', compact: false })
    const employees = wrapper.findAll('.drlv-employee')
    const warnEmployee = employees.find((e) => e.find('.drlv-employee-status--warn').exists())
    expect(warnEmployee).toBeTruthy()
    expect(warnEmployee!.find('.drlv-employee-status').text()).toBe('本机缺包')
  })

  it('marks employee as warn when missing from catalog', async () => {
    statusRef.value.missingCatalogIds = ['e2']
    const wrapper = await mountView({ surface: 'workflow-visualization', compact: false })
    const employees = wrapper.findAll('.drlv-employee')
    const warnEmployee = employees.find((e) => e.find('.drlv-employee-status--warn').exists())
    expect(warnEmployee).toBeTruthy()
    expect(warnEmployee!.find('.drlv-employee-status').text()).toBe('Catalog 缺岗')
  })

  it('calls ensureLoaded on mount', async () => {
    await mountView()
    expect(ensureLoadedMock).toHaveBeenCalled()
  })

  it('uses default surface=workflow-visualization', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.drlv-employees').exists()).toBe(true)
  })

  it('uses default compact=false', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.drlv-employees').exists()).toBe(true)
  })

  it('renders department cards', async () => {
    const wrapper = await mountView()
    expect(wrapper.findAll('.drlv-dept').length).toBeGreaterThan(0)
  })

  it('renders department labels', async () => {
    const wrapper = await mountView()
    const deptHeads = wrapper.findAll('.drlv-dept-head')
    expect(deptHeads.length).toBeGreaterThan(0)
    deptHeads.forEach((h) => {
      expect(h.find('strong').text()).toBeTruthy()
    })
  })

  it('renders "已对齐" for departments with no gaps', async () => {
    const wrapper = await mountView()
    const subs = wrapper.findAll('.drlv-dept-sub')
    const aligned = subs.find((s) => s.text().includes('已对齐'))
    expect(aligned).toBeTruthy()
  })

  it('renders gap count for departments with gaps', async () => {
    statusRef.value.missingLocalIds = ['site-content-editor']
    const wrapper = await mountView()
    const subs = wrapper.findAll('.drlv-dept-sub')
    const withGap = subs.find((s) => s.text().includes('缺口'))
    expect(withGap).toBeTruthy()
  })

  it('renders loop node meta values', async () => {
    const wrapper = await mountView()
    const metas = wrapper.findAll('.drlv-node-meta').map((m) => m.text())
    expect(metas).toContain('2 岗')
  })

  it('renders "当前" meta for active surface node', async () => {
    const wrapper = await mountView({ surface: 'workflow-visualization' })
    const metas = wrapper.findAll('.drlv-node-meta').map((m) => m.text())
    expect(metas).toContain('当前')
  })

  it('renders "观测" meta for non-active surface node', async () => {
    const wrapper = await mountView({ surface: 'workflow-visualization' })
    const metas = wrapper.findAll('.drlv-node-meta').map((m) => m.text())
    expect(metas).toContain('观测')
  })

  it('renders "可运行" meta when ready', async () => {
    readyRef.value = true
    const wrapper = await mountView()
    const metas = wrapper.findAll('.drlv-node-meta').map((m) => m.text())
    expect(metas).toContain('可运行')
  })

  it('renders "待对齐" meta when not ready', async () => {
    readyRef.value = false
    const wrapper = await mountView()
    const metas = wrapper.findAll('.drlv-node-meta').map((m) => m.text())
    expect(metas).toContain('待对齐')
  })
})
