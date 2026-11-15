import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { useIndustryStore } from '@/stores/industry'
import SettingsIntentCard from './SettingsIntentCard.vue'

it('distinguishes pending, failed and empty industry reads', async () => {
  const pinia = createPinia(); setActivePinia(pinia)
  const store = useIndustryStore()
  const view = mount(SettingsIntentCard, { global: { plugins: [pinia] }, props: {
    currentIntentIndustryLabel: '', currentIndustryUnit: '', currentIndustryConfig: null, intentPackageEntries: [],
  } })
  try {
    expect(view.text()).not.toContain('没有可用')
    store.$patch({ settled: true, loading: true }); await nextTick()
    expect(view.text()).not.toContain('没有可用')
    store.$patch({ loading: false, error: '行业读取失败' }); await nextTick()
    expect(view.get('[role="alert"]').text()).toBe('行业读取失败')
    expect(view.text()).not.toContain('没有可用')
    store.$patch({ error: null }); await nextTick()
    expect(view.text()).toContain('当前账号没有可用的行业配置')
  } finally { view.unmount() }
})
