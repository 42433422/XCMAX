import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

// Mock the composable
vi.mock('@/composables/useWorkflowEmployeeDesks', () => ({
  formatWorkDurationShort: vi.fn((ms: number) => {
    if (ms <= 0) return '0m'
    const sec = Math.floor(ms / 1000)
    if (sec < 60) return `${sec}s`
    const min = Math.floor(sec / 60)
    return `${min}m`
  }),
  totalWorkMs: vi.fn(() => 60000),
  useNowMsTicker: vi.fn(() => ({ value: 1000000 })),
  useWorkflowEmployeeDesks: () => ({
    statusLine: vi.fn((row: { enabled: boolean }) =>
      row.enabled ? '运行中' : '副窗未启用'
    ),
    isBusy: vi.fn((row: { enabled: boolean; snapshot?: { visuallyBusy?: boolean } }) =>
      row.enabled && row.snapshot?.visuallyBusy === true
    ),
    desks: { value: [] },
    onDutyDesks: { value: [] },
    employeeIds: { value: [] },
    ariaLabel: vi.fn(),
    processedCount: vi.fn(() => 0),
  }),
}))

// Mock docs loader
vi.mock('@/utils/workflowEmployeeDocs', () => ({
  buildSyntheticManifestWorkflowFlow: vi.fn(() => null),
  getWorkflowEmployeeDocs: vi.fn(() =>
    Promise.resolve({
      flows: [
        {
          id: 'label_print',
          name: '标签打印',
          steps: [
            { label: '步骤1', detail: '详情1' },
            { label: '步骤2', detail: '' },
          ],
        },
      ],
    })
  ),
}))

// Mock mod workflow employees
vi.mock('@/utils/modWorkflowEmployees', () => ({
  findWorkflowEmployeeEntry: vi.fn(() => null),
}))

// Mock child component to avoid side effects
vi.mock('@/components/workflow/YuangongInteractiveWorkstation.vue', () => ({
  default: {
    name: 'YuangongInteractiveWorkstation',
    template: '<div class="yiw-stub" :data-busy="busy" :data-enabled="enabled">{{ statusLine }}</div>',
    props: ['statusLine', 'workflowFullName', 'enabled', 'busy'],
  },
}))

import EmployeeDetailPanel from '@/components/workflow/EmployeeDetailPanel.vue'

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { name: 'chat', path: '/chat', component: { template: '<div/>' } },
      { name: 'print', path: '/print', component: { template: '<div/>' } },
      { name: 'shipment-records', path: '/shipment', component: { template: '<div/>' } },
      { name: 'customers', path: '/customers', component: { template: '<div/>' } },
      { name: 'data-sources', path: '/data-sources', component: { template: '<div/>' } },
    ],
  })
}

function makeRow(overrides = {}) {
  return {
    empId: 'label_print',
    panelTitle: '工作流 · 标签打印',
    shortName: '标签打印',
    enabled: true,
    hostModId: undefined,
    carrierModId: undefined,
    snapshot: {
      stage: '处理中',
      progressLabel: '50%',
      hintLine: '提示信息',
      progressPct: 50,
      visuallyBusy: true,
    },
    session: {
      enabledAt: 900000,
      lifetimeMs: 100000,
      processedCount: 5,
    },
    ...overrides,
  }
}

function mountPanel(row = null) {
  const router = createTestRouter()
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(EmployeeDetailPanel, {
    props: { row },
    global: {
      plugins: [router, pinia],
    },
  })
}

describe('EmployeeDetailPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders aside element with complementary role', () => {
    const wrapper = mountPanel()
    expect(wrapper.find('aside[role="complementary"]').exists()).toBe(true)
  })

  it('shows empty state name when row is null', () => {
    const wrapper = mountPanel(null)
    expect(wrapper.find('.edp-name').text()).toBe('—')
  })

  it('shows employee short name when row is provided', () => {
    const wrapper = mountPanel(makeRow())
    expect(wrapper.find('.edp-name').text()).toBe('标签打印')
  })

  it('shows panel title when row is provided', () => {
    const wrapper = mountPanel(makeRow())
    expect(wrapper.find('.edp-title').text()).toBe('工作流 · 标签打印')
  })

  it('shows dash for panel title when row is null', () => {
    const wrapper = mountPanel(null)
    expect(wrapper.find('.edp-title').text()).toBe('—')
  })

  it('renders kicker text', () => {
    const wrapper = mountPanel()
    expect(wrapper.find('.edp-kicker').text()).toBe('工位特写')
  })

  it('renders stats section with 3 stat items', () => {
    const wrapper = mountPanel(makeRow())
    expect(wrapper.findAll('.edp-stat')).toHaveLength(3)
  })

  it('shows processed count', () => {
    const wrapper = mountPanel(makeRow())
    const stats = wrapper.findAll('.edp-stat-v')
    expect(stats[0].text()).toBe('5')
  })

  it('shows work duration label when enabled', () => {
    const wrapper = mountPanel(makeRow())
    const stats = wrapper.findAll('.edp-stat-v')
    // workLabel uses formatWorkDurationShort mock which returns "1m" for 60000ms
    expect(stats[1].text()).toBe('1m')
  })

  it('shows dash for work duration when not enabled', () => {
    const wrapper = mountPanel(makeRow({ enabled: false, session: undefined }))
    const stats = wrapper.findAll('.edp-stat-v')
    expect(stats[1].text()).toBe('—')
  })

  it('shows stage label from snapshot', () => {
    const wrapper = mountPanel(makeRow())
    const stats = wrapper.findAll('.edp-stat-v')
    expect(stats[2].text()).toBe('处理中')
  })

  it('shows 待命中 when enabled but no snapshot', () => {
    const wrapper = mountPanel(makeRow({ snapshot: undefined }))
    const stats = wrapper.findAll('.edp-stat-v')
    expect(stats[2].text()).toBe('待命中')
  })

  it('shows 已下班 when not enabled', () => {
    const wrapper = mountPanel(makeRow({ enabled: false, snapshot: undefined }))
    const stats = wrapper.findAll('.edp-stat-v')
    expect(stats[2].text()).toBe('已下班')
  })

  it('shows hint line when present', () => {
    const wrapper = mountPanel(makeRow())
    expect(wrapper.find('.edp-hint').exists()).toBe(true)
    expect(wrapper.find('.edp-hint').text()).toBe('提示信息')
  })

  it('hides hint line when not present', () => {
    const wrapper = mountPanel(makeRow({ snapshot: { hintLine: '' } }))
    expect(wrapper.find('.edp-hint').exists()).toBe(false)
  })

  it('hides hint line when not enabled', () => {
    const wrapper = mountPanel(makeRow({ enabled: false, snapshot: undefined }))
    expect(wrapper.find('.edp-hint').exists()).toBe(false)
  })

  it('renders workflow steps section header', () => {
    const wrapper = mountPanel(makeRow())
    expect(wrapper.find('.edp-section-h').text()).toBe('工作流程步骤')
  })

  it('shows loading message before docs are loaded', () => {
    const wrapper = mountPanel(makeRow())
    expect(wrapper.find('.edp-section-empty').text()).toContain('加载中')
  })

  it('renders workflow steps after docs load', async () => {
    const wrapper = mountPanel(makeRow({ empId: 'label_print' }))
    // Wait for onMounted async to complete
    await vi.dynamicImportSettled()
    await wrapper.vm.$nextTick()
    const steps = wrapper.findAll('.edp-flow-step')
    expect(steps.length).toBeGreaterThan(0)
  })

  it('renders step label and detail', async () => {
    const wrapper = mountPanel(makeRow({ empId: 'label_print' }))
    await vi.dynamicImportSettled()
    await wrapper.vm.$nextTick()
    const step = wrapper.findAll('.edp-flow-step')[0]
    expect(step.find('.edp-flow-label').text()).toBe('步骤1')
    expect(step.find('.edp-flow-detail').text()).toBe('详情1')
  })

  it('renders database button with link label', () => {
    const wrapper = mountPanel(makeRow({ empId: 'label_print' }))
    const btn = wrapper.find('.edp-db-btn')
    expect(btn.exists()).toBe(true)
    expect(btn.find('.edp-db-btn-label').text()).toContain('查看标签打印工作台')
  })

  it('disables database button when row is null', () => {
    const wrapper = mountPanel(null)
    const btn = wrapper.find('.edp-db-btn')
    expect(btn.attributes('disabled')).toBeDefined()
  })

  it('enables database button when row is provided', () => {
    const wrapper = mountPanel(makeRow())
    const btn = wrapper.find('.edp-db-btn')
    expect(btn.attributes('disabled')).toBeUndefined()
  })

  it('shows fallback database link for unknown employee', () => {
    const wrapper = mountPanel(makeRow({ empId: 'unknown_emp' }))
    const btn = wrapper.find('.edp-db-btn')
    expect(btn.find('.edp-db-btn-label').text()).toBe('回到智能对话')
  })

  it('clicking database button navigates via router', async () => {
    const wrapper = mountPanel(makeRow({ empId: 'label_print' }))
    const router = wrapper.vm.$.appContext.config.globalProperties.$router
    const pushSpy = vi.spyOn(router, 'push')
    await wrapper.find('.edp-db-btn').trigger('click')
    expect(pushSpy).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'print' })
    )
  })

  it('clicking database button for wechat_msg includes query', async () => {
    const wrapper = mountPanel(makeRow({ empId: 'wechat_msg' }))
    const router = wrapper.vm.$.appContext.config.globalProperties.$router
    const pushSpy = vi.spyOn(router, 'push')
    await wrapper.find('.edp-db-btn').trigger('click')
    expect(pushSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'data-sources',
        query: { source: 'wechat_local_db' },
      })
    )
  })

  it('renders progress bar with correct width', () => {
    const wrapper = mountPanel(makeRow({ snapshot: { progressPct: 75, visuallyBusy: false } }))
    const bar = wrapper.find('.edp-stat-bar-fill')
    expect(bar.attributes('style') || '').toContain('width: 75%')
  })

  it('clamps progress to 0 when negative', () => {
    const wrapper = mountPanel(makeRow({ snapshot: { progressPct: -10 } }))
    const bar = wrapper.find('.edp-stat-bar-fill')
    expect(bar.attributes('style') || '').toContain('width: 0%')
  })

  it('clamps progress to 100 when over 100', () => {
    const wrapper = mountPanel(makeRow({ snapshot: { progressPct: 150 } }))
    const bar = wrapper.find('.edp-stat-bar-fill')
    expect(bar.attributes('style') || '').toContain('width: 100%')
  })

  it('shows 0 progress when not enabled', () => {
    const wrapper = mountPanel(makeRow({ enabled: false, snapshot: undefined }))
    const bar = wrapper.find('.edp-stat-bar-fill')
    expect(bar.attributes('style') || '').toContain('width: 0%')
  })

  it('shows 0 progress when progressPct is not a number', () => {
    const wrapper = mountPanel(makeRow({ snapshot: { progressPct: NaN } }))
    const bar = wrapper.find('.edp-stat-bar-fill')
    expect(bar.attributes('style') || '').toContain('width: 0%')
  })

  it('applies busy class to progress bar when visually busy', () => {
    const wrapper = mountPanel(makeRow({ snapshot: { visuallyBusy: true, progressPct: 50 } }))
    expect(wrapper.find('.edp-stat-bar-fill').classes()).toContain('edp-stat-bar-fill--busy')
  })

  it('does not apply busy class when not visually busy', () => {
    const wrapper = mountPanel(makeRow({ snapshot: { visuallyBusy: false, progressPct: 50 } }))
    expect(wrapper.find('.edp-stat-bar-fill').classes()).not.toContain('edp-stat-bar-fill--busy')
  })

  it('shows processed count as 0 when session is undefined', () => {
    const wrapper = mountPanel(makeRow({ session: undefined }))
    expect(wrapper.findAll('.edp-stat-v')[0].text()).toBe('0')
  })

  it('shows processed count as 0 when processedCount is negative', () => {
    const wrapper = mountPanel(makeRow({ session: { processedCount: -5 } }))
    expect(wrapper.findAll('.edp-stat-v')[0].text()).toBe('0')
  })

  it('renders stat sub text for enabled employee', () => {
    const wrapper = mountPanel(makeRow())
    const subs = wrapper.findAll('.edp-stat-sub')
    expect(subs[1].text()).toBe('副窗启用累计')
  })

  it('renders stat sub text for disabled employee', () => {
    const wrapper = mountPanel(makeRow({ enabled: false, session: undefined }))
    const subs = wrapper.findAll('.edp-stat-sub')
    expect(subs[1].text()).toBe('副窗未启用')
  })

  it('sets aria-label on aside with employee name', () => {
    const wrapper = mountPanel(makeRow())
    expect(wrapper.find('aside').attributes('aria-label')).toContain('标签打印')
  })

  it('sets generic aria-label when row is null', () => {
    const wrapper = mountPanel(null)
    expect(wrapper.find('aside').attributes('aria-label')).toBe('工位详情')
  })

  it('shows empty steps message when docs loaded but no steps', async () => {
    const wrapper = mountPanel(makeRow({ empId: 'nonexistent_id' }))
    await vi.dynamicImportSettled()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.edp-section-empty').text()).toContain('扩展提供专属流程')
  })
})
