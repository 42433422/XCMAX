import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const toggleMock = vi.fn()
const statusLineMock = vi.fn((row: { enabled: boolean; snapshot?: { progressPct?: number } }) =>
  row.enabled ? '运行中' : '已停止',
)
const isBusyMock = vi.fn((row: { snapshot?: { busy?: boolean } }) => Boolean(row.snapshot?.busy))

vi.mock('@/stores/workflowAiEmployees', () => ({
  useWorkflowAiEmployeesStore: () => ({
    toggle: toggleMock,
  }),
}))

vi.mock('@/composables/useWorkflowEmployeeDesks', () => ({
  useWorkflowEmployeeDesks: () => ({
    statusLine: statusLineMock,
    isBusy: isBusyMock,
  }),
}))

import WorkflowEmployeeInspector from './WorkflowEmployeeInspector.vue'

interface DeskRow {
  empId: string
  shortName: string
  panelTitle: string
  enabled: boolean
  snapshot?: { progressPct?: number; busy?: boolean }
}

function makeRow(overrides: Partial<DeskRow> = {}): DeskRow {
  return {
    empId: 'e1',
    shortName: '员工A',
    panelTitle: '面板标题',
    enabled: false,
    ...overrides,
  }
}

function mountInspector(props: Record<string, unknown> = {}) {
  return mount(WorkflowEmployeeInspector, {
    props: {
      desks: [],
      selectedEmpId: null,
      ...props,
    },
    global: {
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
}

describe('WorkflowEmployeeInspector', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('renders the inspector aside', () => {
    const wrapper = mountInspector()
    expect(wrapper.find('.wfe-inspector').exists()).toBe(true)
  })

  it('renders the heading', () => {
    const wrapper = mountInspector()
    expect(wrapper.find('.wfe-inspector-h').text()).toBe('员工与状态')
  })

  it('renders the lead text', () => {
    const wrapper = mountInspector()
    expect(wrapper.find('.wfe-inspector-lead').text()).toContain('一键托管')
  })

  it('renders no rows when desks is empty', () => {
    const wrapper = mountInspector()
    expect(wrapper.findAll('.wfe-inspector-row')).toHaveLength(0)
  })

  it('renders rows for each desk', () => {
    const wrapper = mountInspector({
      desks: [makeRow({ empId: 'e1' }), makeRow({ empId: 'e2', shortName: '员工B' })],
    })
    expect(wrapper.findAll('.wfe-inspector-row')).toHaveLength(2)
  })

  it('renders short name in row', () => {
    const wrapper = mountInspector({ desks: [makeRow({ shortName: '测试员工' })] })
    expect(wrapper.find('.wfe-inspector-short').text()).toBe('测试员工')
  })

  it('renders panel title in row', () => {
    const wrapper = mountInspector({ desks: [makeRow({ panelTitle: '测试面板' })] })
    expect(wrapper.find('.wfe-inspector-title').text()).toBe('测试面板')
  })

  it('renders status line from composable', () => {
    const wrapper = mountInspector({ desks: [makeRow({ enabled: true })] })
    expect(wrapper.find('.wfe-inspector-status').text()).toBe('运行中')
    expect(statusLineMock).toHaveBeenCalled()
  })

  it('marks row as selected when empId matches selectedEmpId', () => {
    const wrapper = mountInspector({
      desks: [makeRow({ empId: 'e1' })],
      selectedEmpId: 'e1',
    })
    expect(wrapper.find('.wfe-inspector-row').classes()).toContain('wfe-inspector-row--selected')
  })

  it('does not mark row as selected when empId does not match', () => {
    const wrapper = mountInspector({
      desks: [makeRow({ empId: 'e1' })],
      selectedEmpId: 'e2',
    })
    expect(wrapper.find('.wfe-inspector-row').classes()).not.toContain('wfe-inspector-row--selected')
  })

  it('emits update:selectedEmpId with empId when unselected row is clicked', async () => {
    const wrapper = mountInspector({
      desks: [makeRow({ empId: 'e1' })],
      selectedEmpId: null,
    })
    await wrapper.find('.wfe-inspector-hit').trigger('click')
    expect(wrapper.emitted('update:selectedEmpId')).toBeTruthy()
    expect(wrapper.emitted('update:selectedEmpId')![0][0]).toBe('e1')
  })

  it('emits update:selectedEmpId with null when selected row is clicked', async () => {
    const wrapper = mountInspector({
      desks: [makeRow({ empId: 'e1' })],
      selectedEmpId: 'e1',
    })
    await wrapper.find('.wfe-inspector-hit').trigger('click')
    expect(wrapper.emitted('update:selectedEmpId')![0][0]).toBeNull()
  })

  it('calls wfEmp.toggle when toggle button is clicked', async () => {
    const wrapper = mountInspector({ desks: [makeRow({ empId: 'e1' })] })
    await wrapper.find('.wfe-inspector-toggle').trigger('click')
    expect(toggleMock).toHaveBeenCalledWith('e1')
  })

  it('marks toggle as on when row.enabled is true', () => {
    const wrapper = mountInspector({ desks: [makeRow({ enabled: true })] })
    expect(wrapper.find('.wfe-inspector-toggle').classes()).toContain('wfe-inspector-toggle--on')
  })

  it('does not mark toggle as on when row.enabled is false', () => {
    const wrapper = mountInspector({ desks: [makeRow({ enabled: false })] })
    expect(wrapper.find('.wfe-inspector-toggle').classes()).not.toContain('wfe-inspector-toggle--on')
  })

  it('shows "已开" text when enabled', () => {
    const wrapper = mountInspector({ desks: [makeRow({ enabled: true })] })
    expect(wrapper.find('.wfe-inspector-toggle').text()).toBe('已开')
  })

  it('shows "已关" text when disabled', () => {
    const wrapper = mountInspector({ desks: [makeRow({ enabled: false })] })
    expect(wrapper.find('.wfe-inspector-toggle').text()).toBe('已关')
  })

  it('renders busy badge when isBusy returns true', () => {
    isBusyMock.mockReturnValue(true)
    const wrapper = mountInspector({ desks: [makeRow({ snapshot: { busy: true } })] })
    expect(wrapper.find('.wfe-inspector-busy').exists()).toBe(true)
  })

  it('does not render busy badge when isBusy returns false', () => {
    isBusyMock.mockReturnValue(false)
    const wrapper = mountInspector({ desks: [makeRow()] })
    expect(wrapper.find('.wfe-inspector-busy').exists()).toBe(false)
  })

  it('renders progress bar with 0% width when disabled', () => {
    const wrapper = mountInspector({ desks: [makeRow({ enabled: false })] })
    const bar = wrapper.find('.wfe-inspector-progress-bar')
    expect(bar.attributes('style')).toContain('width: 0%')
  })

  it('renders progress bar with percentage when enabled and snapshot has progressPct', () => {
    const wrapper = mountInspector({
      desks: [makeRow({ enabled: true, snapshot: { progressPct: 75 } })],
    })
    const bar = wrapper.find('.wfe-inspector-progress-bar')
    expect(bar.attributes('style')).toContain('width: 75%')
  })

  it('clamps progressPct to 0-100 range', () => {
    const wrapper = mountInspector({
      desks: [makeRow({ enabled: true, snapshot: { progressPct: 150 } })],
    })
    const bar = wrapper.find('.wfe-inspector-progress-bar')
    expect(bar.attributes('style')).toContain('width: 100%')
  })

  it('clamps negative progressPct to 0', () => {
    const wrapper = mountInspector({
      desks: [makeRow({ enabled: true, snapshot: { progressPct: -10 } })],
    })
    const bar = wrapper.find('.wfe-inspector-progress-bar')
    expect(bar.attributes('style')).toContain('width: 0%')
  })

  it('uses 0% when progressPct is not a number', () => {
    const wrapper = mountInspector({
      desks: [makeRow({ enabled: true, snapshot: { progressPct: NaN } })],
    })
    const bar = wrapper.find('.wfe-inspector-progress-bar')
    expect(bar.attributes('style')).toContain('width: 0%')
  })

  it('uses 0% when snapshot is undefined', () => {
    const wrapper = mountInspector({ desks: [makeRow({ enabled: true })] })
    const bar = wrapper.find('.wfe-inspector-progress-bar')
    expect(bar.attributes('style')).toContain('width: 0%')
  })

  it('renders workspace link by default', () => {
    const wrapper = mountInspector({ desks: [] })
    expect(wrapper.find('.wfe-inspector-foot').exists()).toBe(true)
  })

  it('hides workspace link when hideWorkspaceLink is true', () => {
    const wrapper = mountInspector({ desks: [], hideWorkspaceLink: true })
    expect(wrapper.find('.wfe-inspector-foot').exists()).toBe(false)
  })

  it('applies pixel skin class when pixelSkin is true', () => {
    const wrapper = mountInspector({ desks: [], pixelSkin: true })
    expect(wrapper.find('.wfe-inspector').classes()).toContain('wfe-inspector--pixel')
  })

  it('does not apply pixel skin class when pixelSkin is false', () => {
    const wrapper = mountInspector({ desks: [], pixelSkin: false })
    expect(wrapper.find('.wfe-inspector').classes()).not.toContain('wfe-inspector--pixel')
  })

  it('sets aria-current=true on hit button when selected', () => {
    const wrapper = mountInspector({
      desks: [makeRow({ empId: 'e1' })],
      selectedEmpId: 'e1',
    })
    expect(wrapper.find('.wfe-inspector-hit').attributes('aria-current')).toBe('true')
  })

  it('does not set aria-current when not selected', () => {
    const wrapper = mountInspector({
      desks: [makeRow({ empId: 'e1' })],
      selectedEmpId: 'e2',
    })
    expect(wrapper.find('.wfe-inspector-hit').attributes('aria-current')).toBeUndefined()
  })

  it('sets data-emp-id attribute on row', () => {
    const wrapper = mountInspector({ desks: [makeRow({ empId: 'emp-42' })] })
    expect(wrapper.find('.wfe-inspector-row').attributes('data-emp-id')).toBe('emp-42')
  })

  it('sets aria-pressed on toggle based on enabled state', () => {
    const wrapper = mountInspector({ desks: [makeRow({ enabled: true })] })
    expect(wrapper.find('.wfe-inspector-toggle').attributes('aria-pressed')).toBe('true')
  })

  it('sets aria-label on toggle with action and short name', () => {
    const wrapper = mountInspector({ desks: [makeRow({ shortName: '小明', enabled: false })] })
    expect(wrapper.find('.wfe-inspector-toggle').attributes('aria-label')).toContain('小明')
    expect(wrapper.find('.wfe-inspector-toggle').attributes('aria-label')).toContain('开启')
  })
})
