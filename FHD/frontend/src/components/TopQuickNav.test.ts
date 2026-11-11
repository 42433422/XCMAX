import { computed, reactive, ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import TopQuickNav from './TopQuickNav.vue'

const searchProducts = vi.hoisted(() => vi.fn(async () => ({ success: true, data: [] })))
const getCustomers = vi.hoisted(() => vi.fn(async () => ({ success: true, data: [] })))

vi.mock('@/api/products', () => ({ default: { searchProducts } }))
vi.mock('@/api/customers', () => ({ default: { getCustomers } }))
const modsStore = reactive({ activeModId: 'mod-a' })
vi.mock('@/stores/mods', () => ({ useModsStore: () => modsStore }))

const navItems = vi.hoisted(() => [
  { key: 'chat', name: '智能对话', routeName: 'chat', source: 'core', iconClass: 'fa-comments-o' },
  { key: 'im', name: '信息', routeName: 'im', source: 'core', iconClass: 'fa-envelope-o' },
  { key: 'orders', name: '订单管理', routeName: 'orders', source: 'core', iconClass: 'fa-file-text-o' },
  { key: 'customers', name: '客户管理', routeName: 'customers', source: 'core', iconClass: 'fa-users' },
  {
    key: 'workflow-employee-space',
    name: '员工空间',
    routeName: 'workflow-employee-space',
    source: 'child',
    iconClass: 'fa-th-large',
    parentKey: 'employee-workflow',
  },
  { key: 'settings', name: '系统设置', routeName: 'settings', source: 'settings', iconClass: 'fa-cog' },
])

vi.mock('@/composables/useVisibleNavItems', () => ({
  useVisibleNavItems: () => ({
    menuItems: ref([]),
    visibleNavItems: computed(() => navItems),
    coreMenuOverrides: computed(() => new Map()),
  }),
}))

let activeRouter: ReturnType<typeof createRouter>

async function mountNav() {
  activeRouter = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }],
  })
  await activeRouter.push('/')
  await activeRouter.isReady()
  const wrapper = mount(TopQuickNav, {
    attachTo: document.body,
    global: { plugins: [activeRouter] },
  })
  await wrapper.find('input').trigger('focus')
  return wrapper
}

const optionNames = () => [...document.querySelectorAll('.top-quick-nav__option')].map((node) => node.textContent || '')

describe('TopQuickNav', () => {
  it('聚焦后展示全部侧边栏入口', async () => {
    const wrapper = await mountNav()
    const names = optionNames()
    expect(names).toContain('智能对话')
    expect(names).toContain('订单管理')
    expect(names).toContain('员工空间')
    expect(names).toContain('系统设置')
    wrapper.unmount()
  })

  it('按关键词过滤功能名', async () => {
    const wrapper = await mountNav()
    await wrapper.find('input').setValue('订单')
    expect(optionNames()).toEqual(['订单管理'])
    await wrapper.find('input').setValue('不存在的东西')
    expect(document.querySelector('.top-quick-nav__empty')).toBeTruthy()
    wrapper.unmount()
  })

  it('回车选中高亮项并 emit select', async () => {
    const wrapper = await mountNav()
    await wrapper.find('input').setValue('客户')
    await wrapper.find('input').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select')).toEqual([['customers']])
    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('')
    wrapper.unmount()
  })

  it('方向键移动高亮，Escape 关闭下拉', async () => {
    const wrapper = await mountNav()
    const input = wrapper.find('input')
    await input.trigger('keydown', { key: 'ArrowDown' })
    await input.trigger('keydown', { key: 'ArrowDown' })
    const highlighted = [...document.querySelectorAll('.top-quick-nav__option')].findIndex((node) => node.classList.contains('highlighted'))
    expect(highlighted).toBe(2)
    await input.trigger('keydown', { key: 'Escape' })
    expect(document.querySelector('.top-quick-nav__list')).toBeNull()
    wrapper.unmount()
  })

  it('点击选项 emit select 并收起下拉', async () => {
    const wrapper = await mountNav()
    const target = [...document.querySelectorAll('.top-quick-nav__option')].find((node) => (node.textContent || '').includes('系统设置'))
    target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('select')).toEqual([['settings']])
    expect(document.querySelector('.top-quick-nav__list')).toBeNull()
    wrapper.unmount()
  })

  it('跟随视口、方向键和空列表，且空查询回车不跳转', async () => {
    if (typeof Element.prototype.scrollIntoView !== 'function') {
      Element.prototype.scrollIntoView = () => undefined
    }
    const scrollIntoView = vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(() => undefined)
    const wrapper = await mountNav()
    const option = document.querySelector('.top-quick-nav__option')
    option?.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }))
    window.dispatchEvent(new Event('resize'))
    window.dispatchEvent(new Event('scroll'))
    const input = wrapper.find('input').element as HTMLInputElement
    const rect = input.getBoundingClientRect.bind(input)
    Object.defineProperty(input, 'getBoundingClientRect', { configurable: true, value: undefined })
    window.dispatchEvent(new Event('resize'))
    Object.defineProperty(input, 'getBoundingClientRect', { configurable: true, value: rect })

    await wrapper.find('input').trigger('blur')
    await new Promise((resolve) => setTimeout(resolve, 200))
    await wrapper.find('input').trigger('keydown', { key: 'ArrowDown' })
    expect(document.querySelector('.top-quick-nav__list')).toBeTruthy()

    await wrapper.find('input').trigger('keydown', { key: 'ArrowUp' })
    expect(scrollIntoView).toHaveBeenCalled()
    await wrapper.find('input').setValue('不存在的东西')
    await wrapper.find('input').trigger('keydown', { key: 'ArrowDown' })
    await wrapper.find('input').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select')).toBeFalsy()
    wrapper.unmount()
    scrollIntoView.mockRestore()
  })

  it('空查询回车不跳转，输入法确认回车也不跳转', async () => {
    const wrapper = await mountNav()
    await wrapper.find('input').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select')).toBeFalsy()
    await wrapper.find('input').trigger('keydown', { key: 'Enter', isComposing: true })
    await wrapper.find('input').setValue('客户')
    await wrapper.find('input').trigger('keydown', { key: 'Enter', isComposing: true })
    expect(wrapper.emitted('select')).toBeFalsy()
    wrapper.unmount()
  })

  it('按产品型号和客户搜索，点击后打开对应列表并带上定位', async () => {
    searchProducts.mockImplementation(async () => ({
      success: true,
      data: [{ id: 7, model_number: 'A001', name: '阀体' }],
    }))
    getCustomers.mockImplementation(async () => ({
      success: true,
      data: [{ id: 3, customer_name: '华星客户' }],
    }))
    const wrapper = await mountNav()
    const input = wrapper.find('input')
    const waitRecords = async () => {
      await new Promise((resolve) => setTimeout(resolve, 300))
      await flushPromises()
    }
    const clickOption = async (label: string) => {
      const option = [...document.querySelectorAll('.top-quick-nav__option')].find((node) => (node.textContent || '').includes(label))
      option?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
      await flushPromises()
    }

    await input.setValue('A001')
    await waitRecords()
    const names = optionNames()
    expect(names.some((name) => name.includes('产品') && name.includes('A001'))).toBe(true)
    expect(names.some((name) => name.includes('客户') && name.includes('华星客户'))).toBe(true)

    await clickOption('华星客户')
    expect(activeRouter.currentRoute.value.path).toContain('/customers')
    expect(activeRouter.currentRoute.value.query).toMatchObject({ keyword: '华星客户', focus: '3' })

    await input.trigger('focus')
    await input.setValue('A001')
    await waitRecords()
    await clickOption('阀体')
    expect(activeRouter.currentRoute.value.path).toContain('/products')
    expect(activeRouter.currentRoute.value.query).toMatchObject({ keyword: 'A001', focus: '7' })
    wrapper.unmount()
  })

  describe('搜索记录的账号与工作区边界', () => {
    let wrapper: Awaited<ReturnType<typeof mountNav>> | undefined
    const product = { id: 7, model_number: 'A001', name: '旧租户产品' }

    beforeEach(() => {
      vi.useFakeTimers()
      searchProducts.mockReset().mockResolvedValue({ success: true, data: [product] })
      getCustomers.mockReset().mockResolvedValue({ success: true, data: [{ id: 3, customer_name: '旧租户客户' }] })
      modsStore.activeModId = 'mod-a'
      setRuntimeTenantStorageScopeInput({ tenantId: 1 })
    })
    afterEach(() => {
      wrapper?.unmount()
      wrapper = undefined
      vi.useRealTimers()
      setRuntimeTenantStorageScopeInput(null)
    })

    it.each([
      ['账号', () => { productReadAccountEpoch.value++ }],
      ['租户', () => { setRuntimeTenantStorageScopeInput({ tenantId: 2 }) }],
      ['Mod', () => { modsStore.activeModId = 'mod-b' }],
    ] as const)('切换%s立即清除已显示记录，旧选项不能继续跳转', async (_name, changeScope) => {
      wrapper = await mountNav()
      const input = wrapper.find('input')
      await input.setValue('A001')
      await vi.advanceTimersByTimeAsync(250)
      await flushPromises()
      expect(optionNames().join()).toContain('旧租户产品')
      expect(optionNames().join()).toContain('旧租户客户')
      const staleOption = document.querySelector('.top-quick-nav__option')!

      changeScope()
      staleOption.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
      await flushPromises()
      expect(activeRouter.currentRoute.value.path).toBe('/')
      expect((input.element as HTMLInputElement).value).toBe('')
      await input.trigger('focus')
      expect(optionNames().join()).not.toContain('旧租户')
    })

    it('取消旧工作区的防抖，仍允许新工作区搜索', async () => {
      wrapper = await mountNav()
      const input = wrapper.find('input')
      await input.setValue('A001')
      await vi.advanceTimersByTimeAsync(100)
      productReadAccountEpoch.value++
      await vi.advanceTimersByTimeAsync(250)
      expect(searchProducts).not.toHaveBeenCalled()
      expect(getCustomers).not.toHaveBeenCalled()

      searchProducts.mockResolvedValue({ success: true, data: [{ ...product, name: '当前工作区产品' }] })
      getCustomers.mockResolvedValue({ success: true, data: [] })
      await input.trigger('focus')
      await input.setValue('A001')
      await vi.advanceTimersByTimeAsync(250)
      await flushPromises()
      expect(searchProducts).toHaveBeenCalledOnce()
      expect(optionNames().join()).toContain('当前工作区产品')
    })

    it('A → B → A 后丢弃已完成一半的搜索，即使 API 已拒绝另一半旧响应', async () => {
      let rejectOldCustomers!: (reason: Error) => void
      getCustomers.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectOldCustomers = reject }))
      wrapper = await mountNav()
      const input = wrapper.find('input')
      await input.setValue('A001')
      await vi.advanceTimersByTimeAsync(250)
      await flushPromises()
      expect(searchProducts).toHaveBeenCalledOnce()

      productReadAccountEpoch.value++
      productReadAccountEpoch.value++
      rejectOldCustomers(new Error('账号已切换'))
      await flushPromises()
      await input.trigger('focus')
      expect(optionNames().join()).not.toContain('旧租户产品')
      expect((input.element as HTMLInputElement).value).toBe('')
    })
  })
})
