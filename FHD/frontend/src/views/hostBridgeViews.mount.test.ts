import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

const hostStub = {
  HostModBridgeView: {
    props: ['modId', 'view', 'title'],
    template: '<div class="host-bridge" :data-mod="modId" :data-view="view" />',
  },
}

const views = [
  { name: 'BrainView', modId: 'xcagi-planner-bridge', view: 'BrainView' },
  { name: 'OrdersView', modId: 'xcagi-erp-domain-bridge', view: 'OrdersView' },
  { name: 'CustomersView', modId: 'xcagi-erp-domain-bridge', view: 'CustomersView' },
  { name: 'MaterialsView', modId: 'xcagi-erp-domain-bridge', view: 'MaterialsView' },
  { name: 'PrintView', modId: 'xcagi-erp-domain-bridge', view: 'PrintView' },
  { name: 'InventoryView', modId: 'xcagi-erp-domain-bridge', view: 'InventoryView' },
  { name: 'PurchaseView', modId: 'xcagi-erp-domain-bridge', view: 'PurchaseView' },
  { name: 'ToolsView', modId: 'xcagi-office-employee-pack-bridge', view: 'ToolsView' },
  { name: 'TraditionalModeView', modId: 'xcagi-erp-domain-bridge', view: 'TraditionalModeView' },
]

describe('HostModBridge stub views', () => {
  for (const spec of views) {
    it(`${spec.name} mounts HostModBridgeView`, async () => {
      const mod = await import(`./${spec.name}.vue`)
      const wrapper = mount(mod.default, {
        global: { stubs: hostStub },
      })
      const bridge = wrapper.find('.host-bridge')
      expect(bridge.exists()).toBe(true)
      expect(bridge.attributes('data-mod')).toBe(spec.modId)
      expect(bridge.attributes('data-view')).toBe(spec.view)
    })
  }
})
