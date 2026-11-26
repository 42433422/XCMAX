import { computed, reactive, ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import TopQuickNav from './TopQuickNav.vue'
import { resolveErpPagePath } from '@/utils/erpPagePaths'
import {
  defaultWorkspaceCommandPreferences, readWorkspaceCommandPreferences, workspaceCommandStorageKey,
  writeWorkspaceCommandPreferences,
} from '@/utils/workspaceCommandShortcuts'

const searchProducts = vi.hoisted(() => vi.fn(async () => ({ success: true, data: [] })))
const getCustomers = vi.hoisted(() => vi.fn(async () => ({ success: true, data: [] })))
const searchOrders = vi.hoisted(() => vi.fn(async () => ({ success: true, data: [] })))
const fetchEmployeeDirectory = vi.hoisted(() => vi.fn(async () => []))
const listTemplates = vi.hoisted(() => vi.fn(async () => ({ success: true, templates: [] })))

vi.mock('@/api/products', () => ({ default: { searchProducts } }))
vi.mock('@/api/customers', () => ({ default: { getCustomers } }))
vi.mock('@/api/orders', () => ({ default: { searchOrders } }))
vi.mock('@/api/employeeDirectory', () => ({ fetchEmployeeDirectory }))
vi.mock('@/api/templatePreview', () => ({ default: { listTemplates }, templatePreviewApi: { listTemplates } }))
const modsStore = reactive({ activeModId: 'mod-a' })
vi.mock('@/stores/mods', () => ({ useModsStore: () => modsStore }))
const scopedTasks = reactive({ tasks: [] as any[], stale: false })
vi.mock('@/stores/agentTaskCenter', () => ({
  useAgentTaskCenterStore: () => scopedTasks,
}))

const navItems = reactive([
  { key: 'chat', name: '智能对话', routeName: 'chat', source: 'core', iconClass: 'fa-comments-o' },
  { key: 'im', name: '信息', routeName: 'im', source: 'core', iconClass: 'fa-envelope-o' },
  { key: 'orders', name: '订单管理', routeName: 'orders', source: 'core', iconClass: 'fa-file-text-o' },
  { key: 'customers', name: '客户管理', routeName: 'customers', source: 'core', iconClass: 'fa-users' },
  { key: 'products', name: '产品管理', routeName: 'products', source: 'core', iconClass: 'fa-cube' },
  { key: 'template-preview', name: '模板预览', routeName: 'template-preview', source: 'core', iconClass: 'fa-file' },
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
    routes: [
      { path: '/workspaces/:taskId', name: 'task-workspace', component: { template: '<div />' } },
      { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
    ],
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

  it('订单与员工也纳入全线搜索并可跳转', async () => {
    searchOrders.mockResolvedValue({
      success: true,
      data: [{ order_number: 'SO-001', customer_name: '华星客户' }],
    })
    fetchEmployeeDirectory.mockResolvedValue([
      { pack_id: 'emp_cs', label: '客服员工', department: '客服' },
    ] as never)
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

    await input.setValue('SO-001')
    await waitRecords()
    expect(optionNames().join()).toContain('SO-001 · 华星客户')
    await clickOption('SO-001')
    expect(activeRouter.currentRoute.value.path).toContain('/orders')
    expect(activeRouter.currentRoute.value.query).toMatchObject({ keyword: 'SO-001' })

    await input.trigger('focus')
    await input.setValue('客服')
    await waitRecords()
    await clickOption('客服员工')
    expect(wrapper.emitted('select')?.at(-1)).toEqual(['employee-workflow'])

    searchOrders.mockResolvedValue({ success: true, data: [] })
    fetchEmployeeDirectory.mockResolvedValue([])
    wrapper.unmount()
  })

  describe('desktop command entry', () => {
    it('accepts commands from the native bridge only while their destination is available', async () => {
      const unregister = vi.fn()
      let dispatch!: (command: string) => void
      vi.stubGlobal('xcagiDesktop', {
        onWorkspaceCommand(listener: typeof dispatch) { dispatch = listener; return unregister },
      })
      const wrapper = await mountNav()
      const chat = navItems[0]
      const outsideDialog = document.createElement('button')
      outsideDialog.setAttribute('role', 'dialog')
      document.body.append(outsideDialog)
      try {
        outsideDialog.focus()
        dispatch('palette')
        await wrapper.vm.$nextTick()
        expect(document.querySelector('.top-quick-nav--palette')).toBeNull()
        outsideDialog.remove()
        dispatch('palette')
        await wrapper.vm.$nextTick()
        expect(document.querySelector('.top-quick-nav--palette')).toBeTruthy()
        dispatch('tasks')
        expect(wrapper.emitted('command')).toEqual([['tasks']])
        navItems.shift()
        dispatch('chat')
        expect(wrapper.emitted('command')).toEqual([['tasks']])
      } finally {
        if (!navItems.includes(chat)) navItems.unshift(chat)
        outsideDialog.remove()
        wrapper.unmount()
        vi.unstubAllGlobals()
      }
      expect(unregister).toHaveBeenCalledOnce()
    })

    it('traps keyboard focus and persists only the current account’s favorites and shortcuts', async () => {
      vi.stubGlobal('xcagiDesktop', {})
      setRuntimeTenantStorageScopeInput({ localUserId: 11, tenantId: 1 })
      const firstKey = workspaceCommandStorageKey()
      const geometry = vi.spyOn(HTMLElement.prototype, 'getClientRects')
        .mockReturnValue([new DOMRect(0, 0, 20, 20)] as unknown as DOMRectList)
      const wrapper = await mountNav()
      try {
        await wrapper.get('.top-quick-nav__narrow-trigger').trigger('click')
        const palette = document.querySelector<HTMLElement>('.top-quick-nav--palette')!
        const input = palette.querySelector('input')!
        const button = (label: string) => new DOMWrapper(
          [...palette.querySelectorAll('button')].find(item => item.textContent?.includes(label))!,
        )
        const q = new DOMWrapper(input)
        await q.setValue('客户管理')
        await button('设为常用').trigger('click')
        expect(readWorkspaceCommandPreferences(firstKey).favorites).toEqual(['customers'])
        await button('取消常用').trigger('click')
        expect(readWorkspaceCommandPreferences(firstKey).favorites).toEqual([])

        input.focus()
        await q.trigger('keydown', { key: 'Tab', shiftKey: true })
        expect(document.activeElement).toBe(button('Esc 关闭').element)
        await button('Esc 关闭').trigger('keydown', { key: 'Tab' })
        expect(document.activeElement).toBe(input)
        await button('快捷键设置').trigger('click')
        const shortcut = new DOMWrapper(palette.querySelector<HTMLSelectElement>('select[aria-label="打开智能对话快捷键"]')!)
        await shortcut.setValue('Mod+Alt+K')
        expect(readWorkspaceCommandPreferences(firstKey).shortcuts.chat).toBe('Mod+Alt+K')

        window.dispatchEvent(new CustomEvent('xcagi:workspace-nav-visited', { detail: { key: 'customers' } }))
        expect(readWorkspaceCommandPreferences(firstKey).recent).toEqual(['customers'])
        setRuntimeTenantStorageScopeInput({ localUserId: 12, tenantId: 1 })
        const secondKey = workspaceCommandStorageKey()
        window.dispatchEvent(new CustomEvent('xcagi:workspace-nav-visited', { detail: { key: 'products' } }))
        expect(readWorkspaceCommandPreferences(secondKey).recent).toEqual(['products'])
        expect(readWorkspaceCommandPreferences(secondKey).shortcuts.chat).toBe('Mod+Alt+J')
        writeWorkspaceCommandPreferences(secondKey, { ...defaultWorkspaceCommandPreferences(), favorites: ['customers'] })
        window.dispatchEvent(new StorageEvent('storage', { key: secondKey, storageArea: localStorage }))
        await wrapper.vm.$nextTick()
        expect(document.querySelector('.top-quick-nav--palette')).toBeNull()
        await wrapper.get('.top-quick-nav__narrow-trigger').trigger('click')
        await q.setValue('客户管理')
        expect(button('取消常用').exists()).toBe(true)
        localStorage.removeItem(secondKey)
      } finally {
        wrapper.unmount()
        localStorage.removeItem(firstKey)
        setRuntimeTenantStorageScopeInput(null)
        geometry.mockRestore()
        vi.unstubAllGlobals()
      }
    })

    it.each([
      ['Win32', { ctrlKey: true }, 'Control+K'],
      ['MacIntel', { metaKey: true }, 'Meta+K'],
    ] as const)('uses the platform modifier on %s, restores focus and detaches on unmount', async (platform, modifier, label) => {
      const platformSpy = vi.spyOn(navigator, 'platform', 'get').mockReturnValue(platform)
      const desktopDescriptor = Object.getOwnPropertyDescriptor(window, 'xcagiDesktop')
      Object.defineProperty(window, 'xcagiDesktop', { configurable: true, value: {} })
      const origin = document.createElement('button')
      document.body.append(origin)
      const wrapper = await mountNav()
      let unmounted = false
      try {
        const input = wrapper.find('input').element as HTMLInputElement
        vi.spyOn(input, 'getClientRects').mockReturnValue([new DOMRect(0, 0, 420, 32)] as unknown as DOMRectList)
        origin.focus()
        const dispatch = (options: KeyboardEventInit = {}) => {
          const event = new KeyboardEvent('keydown', { key: 'k', bubbles: true, cancelable: true, ...modifier, ...options })
          document.activeElement?.dispatchEvent(event)
          return event
        }
        expect(input.getAttribute('aria-keyshortcuts')).toBe(label)
        expect(dispatch({ isComposing: true }).defaultPrevented).toBe(false)
        expect(document.activeElement).toBe(origin)
        expect(dispatch({ repeat: true }).defaultPrevented).toBe(false)
        expect(dispatch(platform === 'Win32' ? { ctrlKey: false, metaKey: true } : { ctrlKey: true, metaKey: false }).defaultPrevented).toBe(false)
        origin.setAttribute('role', 'dialog')
        expect(dispatch().defaultPrevented).toBe(false)
        origin.removeAttribute('role')
        expect(dispatch().defaultPrevented).toBe(true)
        await wrapper.vm.$nextTick()
        expect(document.activeElement).toBe(input)
        expect(input.getAttribute('aria-expanded')).toBe('true')
        expect(input.getAttribute('aria-activedescendant')).toBe('top-quick-nav-option-0')
        await new DOMWrapper(input).trigger('keydown', { key: 'Escape' })
        expect(document.activeElement).toBe(origin)
        expect(document.querySelector('.top-quick-nav__list')).toBeNull()
        wrapper.unmount()
        unmounted = true
        expect(dispatch().defaultPrevented).toBe(false)
      } finally {
        if (!unmounted) wrapper.unmount()
        origin.remove()
        platformSpy.mockRestore()
        if (desktopDescriptor) Object.defineProperty(window, 'xcagiDesktop', desktopDescriptor)
        else Reflect.deleteProperty(window, 'xcagiDesktop')
      }
    })

    it('ranks recent menu selections without retaining them across account scope changes', async () => {
      const desktopDescriptor = Object.getOwnPropertyDescriptor(window, 'xcagiDesktop')
      Object.defineProperty(window, 'xcagiDesktop', { configurable: true, value: {} })
      const wrapper = await mountNav()
      try {
        const input = wrapper.find('input')
        await input.setValue('系统设置')
        await input.trigger('keydown', { key: 'Enter' })
        expect(wrapper.emitted('select')).toEqual([['settings']])
        await input.trigger('focus')
        expect(optionNames()[0]).toBe('系统设置')
        productReadAccountEpoch.value++
        await input.trigger('focus')
        expect(optionNames()[0]).toBe('智能对话')
      } finally {
        wrapper.unmount()
        if (desktopDescriptor) Object.defineProperty(window, 'xcagiDesktop', desktopDescriptor)
        else Reflect.deleteProperty(window, 'xcagiDesktop')
      }
    })
  })


  it('only searches and navigates business records exposed by the current permitted menu', async () => {
    const itemIndex = navItems.findIndex(item => item.key === 'customers')
    const removed = navItems.splice(itemIndex, 1)
    getCustomers.mockClear()
    const wrapper = await mountNav()
    try {
      await wrapper.find('input').setValue('华星')
      await new Promise((resolve) => setTimeout(resolve, 300))
      await flushPromises()
      expect(getCustomers).not.toHaveBeenCalled()
      expect(optionNames().join()).not.toContain('华星客户')
    } finally {
      wrapper.unmount()
      navItems.splice(itemIndex, 0, ...removed)
    }
  })

  it('removes revoked business records immediately and rejects in-flight results even after regrant', async () => {
    const wrapper = await mountNav()
    const index = navItems.findIndex(item => item.key === 'customers')
    const original = navItems[index]
    let resolveOld!: (value: any) => void
    try {
      getCustomers.mockResolvedValueOnce({ success: true, data: [{ id: 98, customer_name: 'RevokedCustomer' }] } as never)
      await wrapper.find('input').setValue('RevokedCustomer')
      await vi.waitFor(() => expect(optionNames().join()).toContain('RevokedCustomer'))
      const stale = [...document.querySelectorAll('.top-quick-nav__option')].find(n => n.textContent?.includes('RevokedCustomer'))!
      navItems.splice(index, 1)
      stale.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
      await flushPromises()
      expect(optionNames().join()).not.toContain('RevokedCustomer')
      expect(activeRouter.currentRoute.value.path).toBe('/')
      navItems.splice(index, 0, original)
      getCustomers.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
      getCustomers.mockResolvedValue({ success: true, data: [] })
      await wrapper.find('input').setValue('OldInFlight')
      await vi.waitFor(() => expect(resolveOld).toBeTypeOf('function'))
      navItems.splice(index, 1)
      navItems.splice(index, 0, original)
      resolveOld({ success: true, data: [{ id: 99, customer_name: 'OldInFlight' }] })
      await flushPromises()
      expect(optionNames().join()).not.toContain('OldInFlight')
    } finally {
      if (!navItems.some(item => item.key === original.key)) navItems.splice(index, 0, original)
      wrapper.unmount()
    }
  })

  it('searches the same scoped task snapshot in a normal web shell and excludes stale tasks', async () => {
    scopedTasks.tasks = [{ task_id: 'web-task', title: 'WebScopedTask', conversation_id: 'web-conv', status: 'running' }]
    const wrapper = await mountNav()
    try {
      await wrapper.find('input').setValue('WebScopedTask')
      expect(optionNames().join()).toContain('WebScopedTask')
      const old = [...document.querySelectorAll('.top-quick-nav__option')].find(n => n.textContent?.includes('WebScopedTask'))!
      scopedTasks.stale = true
      old.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
      await flushPromises()
      expect(optionNames().join()).not.toContain('WebScopedTask')
      expect(activeRouter.currentRoute.value.path).toBe('/')
      scopedTasks.stale = false
      await flushPromises()
      const current = [...document.querySelectorAll('.top-quick-nav__option')].find(n => n.textContent?.includes('WebScopedTask'))!
      current.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
      await flushPromises()
      expect(activeRouter.currentRoute.value.params.taskId).toBe('web-task')
      expect(activeRouter.currentRoute.value.query.conversation).toBe('web-conv')
    } finally {
      wrapper.unmount()
      scopedTasks.tasks = []
      scopedTasks.stale = false
    }
  })

  it('opens task records from the existing read-only task snapshot without executing a tool', async () => {
    const savedDesktop = Object.getOwnPropertyDescriptor(window, 'xcagiDesktop')
    Object.defineProperty(window, 'xcagiDesktop', { configurable: true, value: {} })
    scopedTasks.tasks = [{
      task_id: 'task-101', title: '核对考勤表', status: 'running',
      conversation_id: 'conv-101', attempt: 1, run_count: 1,
    }]
    const wrapper = await mountNav()
    try {
      await wrapper.find('input').setValue('核对考勤表')
      const task = [...document.querySelectorAll('.top-quick-nav__option')].find((node) => node.textContent?.includes('核对考勤表'))
      expect(task).toBeTruthy()
      task?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
      await flushPromises()
      expect(activeRouter.currentRoute.value.name).toBe('task-workspace')
      expect(activeRouter.currentRoute.value.params.taskId).toBe('task-101')
      expect(activeRouter.currentRoute.value.query.conversation).toBe('conv-101')
      expect(wrapper.emitted('command')).toBeFalsy()
    } finally {
      wrapper.unmount()
      scopedTasks.tasks = []
      if (savedDesktop) Object.defineProperty(window, 'xcagiDesktop', savedDesktop)
      else Reflect.deleteProperty(window, 'xcagiDesktop')
    }
  })

  it.each([
    ['customer', 'QnavCustomer', '/customers', null],
    ['product', 'QnavProduct', '/products', null],
    ['order', 'QnavOrder', '/orders', null],
    ['employee', 'QnavEmployee', '/', 'employee-workflow'],
    ['template', 'QnavTemplate', '/', 'template-preview'],
  ] as const)('dismisses the desktop palette and scrim after choosing a %s record', async (_kind, query, path, navKey) => {
    const savedDesktop = Object.getOwnPropertyDescriptor(window, 'xcagiDesktop')
    Object.defineProperty(window, 'xcagiDesktop', { configurable: true, value: {} })
    searchProducts.mockResolvedValueOnce({ success: true, data: [{ id: 31, model_number: 'QnavProduct' }] } as never)
    getCustomers.mockResolvedValueOnce({ success: true, data: [{ id: 32, customer_name: 'QnavCustomer' }] } as never)
    searchOrders.mockResolvedValueOnce({ success: true, data: [{ order_number: 'QnavOrder' }] } as never)
    fetchEmployeeDirectory.mockResolvedValueOnce([{ pack_id: 'employee-qnav', label: 'QnavEmployee' }] as never)
    listTemplates.mockResolvedValueOnce({ success: true, templates: [{ id: 33, name: 'QnavTemplate' }] } as never)
    const wrapper = await mountNav()
    try {
      const key = new KeyboardEvent('keydown', { key: 'k', ctrlKey: !/Mac/i.test(navigator.platform),
        metaKey: /Mac/i.test(navigator.platform), bubbles: true, cancelable: true })
      document.activeElement?.dispatchEvent(key)
      await wrapper.vm.$nextTick()
      expect(document.querySelector('.top-quick-nav--palette')).toBeTruthy()
      expect(document.querySelector('.top-quick-nav__scrim')).toBeTruthy()
      const input = document.querySelector<HTMLInputElement>('.top-quick-nav--palette input')!
      await new DOMWrapper(input).setValue(query)
      await vi.waitFor(() => expect(optionNames().join()).toContain(query))
      const record = [...document.querySelectorAll('.top-quick-nav__option')]
        .find(node => node.textContent?.includes(query))
      expect(record).toBeTruthy()
      record?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
      await flushPromises()
      expect(document.querySelector('.top-quick-nav--palette')).toBeNull()
      expect(document.querySelector('.top-quick-nav__scrim')).toBeNull()
      expect(document.querySelector('.top-quick-nav__list')).toBeNull()
      expect(activeRouter.currentRoute.value.path).toBe(resolveErpPagePath(path))
      if (navKey) expect(wrapper.emitted('select')).toContainEqual([navKey])
    } finally {
      wrapper.unmount()
      sessionStorage.removeItem('xcagi_template_search_keyword')
      if (savedDesktop) Object.defineProperty(window, 'xcagiDesktop', savedDesktop)
      else Reflect.deleteProperty(window, 'xcagiDesktop')
    }
  })

  it('provides a keyboard focus-trapped command panel, editable shortcuts and safe commands', async () => {
    const savedDesktop = Object.getOwnPropertyDescriptor(window, 'xcagiDesktop')
    Object.defineProperty(window, 'xcagiDesktop', { configurable: true, value: {} })
    const wrapper = await mountNav()
    try {
      const input = wrapper.find('input').element as HTMLInputElement
      const key = new KeyboardEvent('keydown', { key: 'k', ctrlKey: !/Mac/i.test(navigator.platform),
        metaKey: /Mac/i.test(navigator.platform), bubbles: true, cancelable: true })
      document.activeElement?.dispatchEvent(key)
      await wrapper.vm.$nextTick()
      expect(key.defaultPrevented).toBe(true)
      expect(document.querySelector('.top-quick-nav--palette')).toBeTruthy()
      const settings = [...document.querySelectorAll('.top-quick-nav__footer button')]
        .find((button) => button.textContent?.includes('快捷键设置')) as HTMLButtonElement
      settings.click()
      await wrapper.vm.$nextTick()
      const chatShortcut = document.querySelector('select[aria-label="打开智能对话快捷键"]') as HTMLSelectElement
      expect(chatShortcut).toBeTruthy()
      chatShortcut.value = 'Mod+K'
      chatShortcut.dispatchEvent(new Event('change', { bubbles: true }))
      await wrapper.vm.$nextTick()
      expect(document.querySelector('.top-quick-nav__settings [role="alert"]')?.textContent).toContain('已分配')
      expect(chatShortcut.value).toBe('Mod+Alt+J')
      const reset = [...document.querySelectorAll('.top-quick-nav__settings button')]
        .find((button) => button.textContent?.includes('恢复默认')) as HTMLButtonElement
      reset.click()
      await wrapper.vm.$nextTick()
      expect(document.querySelector('.top-quick-nav__settings [role="alert"]')).toBeNull()
      input.focus()
      const paletteInput = new DOMWrapper(input)
      await paletteInput.setValue('打开智能对话')
      await paletteInput.trigger('keydown', { key: 'Enter' })
      expect(wrapper.emitted('command')).toContainEqual(['chat'])
      expect(document.querySelector('.top-quick-nav--palette')).toBeNull()
    } finally {
      wrapper.unmount()
      if (savedDesktop) Object.defineProperty(window, 'xcagiDesktop', savedDesktop)
      else Reflect.deleteProperty(window, 'xcagiDesktop')
    }
  })

})
