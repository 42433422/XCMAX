import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

// OtherToolsView 动态导入 @admin-console-inject/views/DutyRosterGraphView.vue，
// 该路径在测试环境不存在，需要 mock
vi.mock('@admin-console-inject/views/DutyRosterGraphView.vue', () => ({
  default: {
    template: '<div class="duty-roster-stub" />',
  },
}))

const hostStub = {
  HostModBridgeView: {
    props: ['modId', 'view', 'title'],
    template: '<div class="host-bridge" :data-mod="modId" :data-view="view" :data-title="title" />',
  },
}

const hostBridgeViews = [
  { name: 'ApprovalFlowManagementView', modId: 'xcagi-approval-bridge', view: 'ApprovalFlowManagementView', title: '审批' },
  { name: 'ApprovalHubView', modId: 'xcagi-approval-bridge', view: 'ApprovalHubView', title: '审批' },
  { name: 'ApprovalRulesView', modId: 'xcagi-approval-bridge', view: 'ApprovalRulesView', title: '审批' },
  { name: 'ApprovalWorkspaceView', modId: 'xcagi-approval-bridge', view: 'ApprovalWorkspaceView', title: '审批' },
  { name: 'BatchAnalyzeView', modId: 'xcagi-erp-domain-bridge', view: 'BatchAnalyzeView', title: 'ERP 业务页' },
  { name: 'BusinessDockingView', modId: 'xcagi-erp-domain-bridge', view: 'BusinessDockingView', title: 'ERP 业务页' },
  { name: 'ChatDebugView', modId: 'xcagi-planner-bridge', view: 'ChatDebugView', title: 'Planner 页' },
  { name: 'LabelEditorView', modId: 'xcagi-erp-domain-bridge', view: 'LabelEditorView', title: 'ERP 业务页' },
  { name: 'TemplatePreviewView', modId: 'xcagi-erp-domain-bridge', view: 'TemplatePreviewView', title: 'ERP 业务页' },
  { name: 'WechatContactsView', modId: 'xcagi-erp-domain-bridge', view: 'WechatContactsView', title: 'ERP 业务页' },
  { name: 'WorkflowVisualizationView', modId: 'xcagi-workflow-visualization-bridge', view: 'WorkflowVisualizationView', title: '流程可视化' },
]

describe('HostModBridge stub views (zero coverage)', () => {
  for (const spec of hostBridgeViews) {
    it(`${spec.name} mounts HostModBridgeView with correct props`, async () => {
      const mod = await import(`./${spec.name}.vue`)
      const wrapper = mount(mod.default, {
        global: { stubs: hostStub },
      })
      const bridge = wrapper.find('.host-bridge')
      expect(bridge.exists()).toBe(true)
      expect(bridge.attributes('data-mod')).toBe(spec.modId)
      expect(bridge.attributes('data-view')).toBe(spec.view)
      expect(bridge.attributes('data-title')).toBe(spec.title)
    })
  }
})

describe('OtherToolsView', () => {
  it('renders HostModBridgeView when not admin console spa', async () => {
    const mod = await import('./OtherToolsView.vue')
    const wrapper = mount(mod.default, {
      global: {
        stubs: {
          ...hostStub,
          DutyRosterGraphView: true,
        },
      },
    })
    const bridge = wrapper.find('.host-bridge')
    expect(bridge.exists()).toBe(true)
    expect(bridge.attributes('data-mod')).toBe('xcagi-office-employee-pack-bridge')
    expect(bridge.attributes('data-view')).toBe('OtherToolsView')
  })
})

describe('EmployeeWorkspaceView', () => {
  it('renders page with title and scene', async () => {
    const mod = await import('./EmployeeWorkspaceView.vue')
    const wrapper = mount(mod.default, {
      global: {
        stubs: {
          EmployeeWorkspaceScene: {
            template: '<div class="stub-scene" />',
          },
        },
      },
    })
    expect(wrapper.find('#view-workflow-employee-space').exists()).toBe(true)
    expect(wrapper.find('.ews-page-title').text()).toBe('员工空间')
    expect(wrapper.find('.ews-page-sub').text()).toContain('像素入口')
    expect(wrapper.find('.stub-scene').exists()).toBe(true)
  })
})

describe('ModelPaymentView', () => {
  it('renders a placeholder div and redirects to settings on mount', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'home', component: { template: '<div />' } },
        { path: '/settings', name: 'settings', component: { template: '<div />' } },
      ],
    })
    const pushSpy = vi.spyOn(router, 'replace')
    const mod = await import('./ModelPaymentView.vue')
    mount(mod.default, {
      global: { plugins: [router] },
    })
    expect(pushSpy).toHaveBeenCalledWith({
      name: 'settings',
      query: { section: 'model-payment' },
    })
    pushSpy.mockRestore()
  })
})

describe('TencentDocEmbedView', () => {
  it('renders placeholder section when VITE_TENCENT_DOC_EMBED_URL not configured', async () => {
    const mod = await import('./TencentDocEmbedView.vue')
    const wrapper = mount(mod.default)
    expect(wrapper.find('.tdoc-poc').exists()).toBe(true)
    expect(wrapper.find('h1').text()).toContain('在线文档 PoC')
    expect(wrapper.find('.tdoc-placeholder').exists()).toBe(true)
    expect(wrapper.find('iframe').exists()).toBe(false)
  })

  it('sets document title on mount', async () => {
    const mod = await import('./TencentDocEmbedView.vue')
    mount(mod.default)
    expect(document.title).toBe('在线文档 PoC')
  })
})

describe('adminDutyRosterGraphView.stub', () => {
  it('renders an empty div', async () => {
    const mod = await import('./adminDutyRosterGraphView.stub.vue')
    const wrapper = mount(mod.default)
    expect(wrapper.find('div').exists()).toBe(true)
  })
})
