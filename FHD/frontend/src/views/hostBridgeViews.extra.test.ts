import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

const hostStub = {
  HostModBridgeView: {
    props: ['modId', 'view', 'title'],
    template: '<div class="host-bridge" :data-mod="modId" :data-view="view" />',
  },
}

const extraViews = [
  'CreateOrderView',
  'ShipmentRecordsView',
  'DataSourcesView',
  'PrinterListView',
  'KittenFinanceView',
  'TraditionalModeView',
  'EnterpriseCustomerServiceView',
  'InternalCustomerServiceView',
]

describe('additional HostModBridge stub views', () => {
  for (const name of extraViews) {
    it(`${name} mounts`, async () => {
      const mod = await import(`./${name}.vue`)
      const wrapper = mount(mod.default, { global: { stubs: hostStub } })
      expect(wrapper.find('.host-bridge').exists()).toBe(true)
    })
  }
})

describe('AIEcosystemView', () => {
  it('renders launcher grid', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: { template: '<div />' } }],
    })
    const mod = await import('./AIEcosystemView.vue')
    const wrapper = mount(mod.default, {
      global: {
        plugins: [router],
        stubs: {
          KittenAnalyzerView: true,
          AIOpenPanel: true,
          KittenLauncherIcon: true,
          AiOpenLauncherIcon: true,
          ProductionEmployeeLauncherIcon: true,
          ModStoreLauncherIcon: true,
        },
      },
    })
    expect(wrapper.text()).toContain('AI生态应用')
    expect(wrapper.find('.launcher-grid').exists()).toBe(true)
  })
})
