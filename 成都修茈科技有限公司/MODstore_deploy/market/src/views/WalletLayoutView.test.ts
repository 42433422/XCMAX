import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import WalletLayoutView from './WalletLayoutView.vue'

describe('WalletLayoutView', () => {
  it('renders wallet tabs', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'wallet', component: { template: '<div />' } },
        { path: '/purchased', name: 'wallet-purchased', component: { template: '<div />' } },
      ],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(WalletLayoutView, {
      global: { plugins: [router] },
    })

    expect(wrapper.text()).toContain('资金与记录')
    expect(wrapper.text()).toContain('已购资产')
    expect(wrapper.find('.wallet-tabs').exists()).toBe(true)
  })
})
