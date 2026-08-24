import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ModRequiredView from './ModRequiredView.vue'

const RouterLinkStub = {
  props: ['to'],
  template: '<a><slot /></a>',
}

function mountView(modId: string) {
  return mount(ModRequiredView, {
    props: { modId, title: 'ERP 业务页' },
    global: {
      stubs: { RouterLink: RouterLinkStub },
    },
  })
}

describe('ModRequiredView', () => {
  it.each(['xcagi-erp-domain-bridge', 'xcagi-approval-bridge'])(
    'treats %s as a built-in component instead of a store extension',
    (modId) => {
      const wrapper = mountView(modId)

      expect(wrapper.text()).toContain('系统组件暂不可用')
      expect(wrapper.text()).toContain('内置业务组件未能正确加载')
      expect(wrapper.text()).not.toContain('员工商店')
      expect(wrapper.text()).not.toContain('FHD/mods')
    },
  )

  it('keeps the store action for genuinely optional extensions without exposing developer paths', () => {
    const wrapper = mountView('optional-industry-mod')

    expect(wrapper.text()).toContain('ERP 业务页')
    expect(wrapper.text()).toContain('打开员工商店')
    expect(wrapper.text()).not.toContain('FHD/mods')
  })
})
