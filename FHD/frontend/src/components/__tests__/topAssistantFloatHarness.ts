import { vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory, type Router } from 'vue-router'
import { defineComponent, h } from 'vue'
import TopAssistantFloat from '../TopAssistantFloat.vue'

// Shared Vue/transport fixtures; each suite retains its API spies and scope mocks.

const RouterLinkStub = defineComponent({
  name: 'RouterLinkStub',
  props: { to: { type: [String, Object], default: '/' } },
  setup:
    (props, { slots }) =>
    () =>
      h('a', { href: typeof props.to === 'string' ? props.to : '#' }, slots.default?.()),
})

const ExcelPreviewStub = defineComponent({
  name: 'ExcelPreview',
  setup() {
    return () => h('div', { class: 'excel-preview-stub' })
  },
})

vi.mock('@/tutorial/promptAdvancedTutorial', () => ({
  launchAdvancedDriverTour: vi.fn(async () => undefined),
}))

vi.mock('@/composables/useTutorialCatalog', () => ({
  useTutorialCatalog: () => ({
    tutorialTracks: [
      {
        id: 'host',
        title: '宿主入门',
        summary: '认识XC',
        description: '宿主入门说明',
        recommended: true,
      },
      { id: 'advanced', title: '进阶', summary: '进阶教程', description: '进阶说明' },
    ],
    advancedTrackHint: '进阶路线提示',
    buildContext: () => ({ industryId: '考勤', mods: [], visibleNav: [] }),
  }),
}))

vi.mock('@/composables/useWorkflowModsRuntimeContext', () => ({
  useWorkflowModsRuntimeContext: () => ({ modWorkflowEmployeesActive: { value: false } }),
}))

vi.mock('@/composables/useWorkflowPanoramaNavVisible', () => ({
  useWorkflowPanoramaNavVisible: () => ({ showWorkflowPanoramaNav: { value: false } }),
}))

vi.mock('@/utils/workflowNav', () => ({
  resolveWorkflowVisualizationLocation: vi.fn(() => ({ name: 'workflow-visualization' })),
}))

vi.mock('@/composables/useEnterpriseScopedWorkflowRegistry', () => ({
  useEnterpriseScopedWorkflowRegistry: () => ({
    scopedRegistryEntries: {
      value: [{ id: 'wechat_msg' }, { id: 'label_print' }, { id: 'receipt_confirm' }],
    },
  }),
}))

vi.mock('@/utils/workflowEmployeeRegistry', () => ({
  loadWorkflowEmployeeRegistry: vi.fn(async () => ({ version: 1, employees: [] })),
  loadWorkflowEmployeeRegistryCached: vi.fn(async () => ({ version: 1, employees: [] })),
  mergeModManifestEntries: vi.fn((registry: { employees: unknown[] }) => registry.employees),
  resolveLabel: (entry: { id: string }, _resolver: (k: string) => string) => {
    const map: Record<string, string> = {
      wechat_msg: '微信消息员工',
      label_print: '标签打印员工',
      receipt_confirm: '收货确认员工',
    }
    return map[entry.id] || entry.id
  },
}))

vi.mock('@/utils/syncEnterpriseWorkflowRegistry', () => ({
  syncEnterpriseWorkflowRegistry: vi.fn(async () => undefined),
}))

vi.mock('@/constants/productFlow', () => ({
  DEFAULT_TUTORIAL_TRACK_ID: 'host',
}))

vi.mock('@/constants/workflowEmployeeMods', () => ({
  WORKFLOW_EMPLOYEE_IDS: ['wechat_msg', 'label_print', 'receipt_confirm', 'shipment_mgmt'],
}))

export function makeFetchResponse(body: unknown = { ok: true }, ok = true) {
  return {
    ok,
    status: ok ? 200 : 500,
    headers: { get: () => 'application/json' },
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
}

function createTestRouter() {
  const names = [
    'home',
    'login',
    'register',
    'settings',
    'mod-store',
    'products',
    'product-onboarding',
    'chat',
    'dashboard',
    'workflow-visualization',
    'shipment-records',
    'customers',
    'template-preview',
    'materials',
    'inventory',
    'approval-hub',
  ]
  const EmptyComp = defineComponent({ setup: () => () => h('div') })
  const routes = names.map((name) => ({ path: `/${name}`, name, component: EmptyComp }))
  routes.push({ path: '/', name: 'home', component: EmptyComp })
  routes.push({ path: '/:pathMatch(.*)*', name: 'fallback', component: EmptyComp })
  return createRouter({ history: createMemoryHistory(), routes })
}

export async function mountComponent(options: { router?: Router } = {}) {
  const router = options.router || createTestRouter()
  await router.push('/chat')
  await router.isReady()
  const wrapper = mount(TopAssistantFloat, {
    global: {
      plugins: [router],
      stubs: {
        RouterLink: RouterLinkStub,
        ExcelPreview: ExcelPreviewStub,
        Teleport: true,
      },
    },
  })
  await flushPromises()
  return { wrapper, router, vm: wrapper.vm }
}
