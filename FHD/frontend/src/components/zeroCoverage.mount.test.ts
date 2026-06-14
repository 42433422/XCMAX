import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'

const zeroCoverageComponents = [
  { path: '@/components/lan/LanGatePanel.vue', name: 'LanGatePanel', props: {} },
  { path: '@/components/FileImport.vue', name: 'FileImport', props: {} },
  { path: '@/components/template/FieldEditor.vue', name: 'FieldEditor', props: {} },
  { path: '@/components/ShipmentPrintPreview.vue', name: 'ShipmentPrintPreview', props: {} },
  { path: '@/components/TtsSetupBanner.vue', name: 'TtsSetupBanner', props: {} },
  { path: '@/components/template/FileUploadStep.vue', name: 'FileUploadStep', props: {} },
  { path: '@/components/workflow/WorkflowDemo.vue', name: 'WorkflowDemo', props: {} },
  { path: '@/components/workflow/EmployeeWorkspaceScene.vue', name: 'EmployeeWorkspaceScene', props: {} },
  { path: '@/components/chat/MessageBody.vue', name: 'MessageBody', props: { content: 'hello', role: 'user' } },
]

describe('zero-coverage components mount', () => {
  for (const spec of zeroCoverageComponents) {
    it(`${spec.name} mounts`, async () => {
      setActivePinia(createPinia())
      const router = createRouter({
        history: createMemoryHistory(),
        routes: [{ path: '/', component: { template: '<div />' } }],
      })
      const mod = await import(spec.path)
      const wrapper = mount(mod.default, {
        props: spec.props,
        global: {
          plugins: [router],
          stubs: {
            RouterLink: true,
            Teleport: true,
            Modal: true,
            ConfirmDialog: true,
            DataTable: true,
            OptimizedChatMessage: true,
            ElButton: true,
            ElInput: true,
            ElSelect: true,
            ElOption: true,
            ElTabs: true,
            ElTabPane: true,
            ElSwitch: true,
            ElAlert: true,
            ElCard: true,
            ElTag: true,
            ElDivider: true,
            ElForm: true,
            ElFormItem: true,
            KittenAnalyzerView: true,
            AIOpenPanel: true,
          },
        },
      })
      expect(wrapper.exists()).toBe(true)
    })
  }
})
