import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { nextTick, type Component } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App.vue'
import AdminDatabaseView from './AdminDatabaseView.vue'
import AdminView from './AdminView.vue'
import AiStoreView from './AiStoreView.vue'
import CatalogDetailView from './CatalogDetailView.vue'
import DbViewerView from './DbViewerView.vue'
import HomeView from './HomeView.vue'
import LoginByEmailView from './LoginByEmailView.vue'
import LoginView from './LoginView.vue'
import ModAuthoringView from './ModAuthoringView.vue'
import MyStoreView from './MyStoreView.vue'
import OrderDetailView from './OrderDetailView.vue'
import PaymentCheckoutView from './PaymentCheckoutView.vue'
import PaymentPlansView from './PaymentPlansView.vue'
import RegisterView from './RegisterView.vue'
import RepositoryView from './RepositoryView.vue'
import WalletView from './WalletView.vue'
import WorkbenchView from './WorkbenchView.vue'

const apiResult = {
  success: true,
  data: [],
  items: [],
  catalog: [],
  users: [],
  wallets: [],
  transactions: [],
  plans: [],
  orders: [],
  total: 0,
  balance: 0,
  facets: {},
  user: { id: 1, username: 'admin', is_admin: true },
}

const apiMockState = vi.hoisted(() => ({
  reject: false,
  calls: [] as unknown[][],
  responses: {} as Record<string, unknown>,
}))

vi.mock('../api', () => ({
  api: new Proxy(
    {},
    {
      get: (_target, property) =>
        vi.fn(async (...args: unknown[]) => {
          apiMockState.calls.push([String(property), ...args])
          if (apiMockState.reject) throw new Error(`mock ${String(property)} failure`)
          if (Object.prototype.hasOwnProperty.call(apiMockState.responses, String(property))) {
            const configured = apiMockState.responses[String(property)]
            if (configured instanceof Error) throw configured
            return configured
          }
          switch (String(property)) {
            case 'catalogDetail':
              return {
                id: 1,
                name: 'Starter MOD',
                pkg_id: 'starter.mod',
                version: '1.0.0',
                industry: '通用',
                artifact: 'workflow',
                description: 'A test catalog item',
                price: 0,
                purchased: true,
              }
            case 'paymentQuery':
              return {
                id: 'order-1',
                order_id: 'order-1',
                status: 'paid',
                subject: 'Starter plan',
                total_amount: 10,
                created_at: '2026-08-17T00:00:00Z',
                paid_at: '2026-08-17T00:01:00Z',
              }
            case 'paymentCheckout':
              return { ok: false, message: 'checkout unavailable in component test' }
            case 'getMod':
              return { id: 'demo', manifest: {}, files: [] }
            case 'getModAuthoringSummary':
              return { files: [], warnings: [], validation: { errors: [], warnings: [] } }
            case 'getModFile':
              return { content: '' }
            case 'putModManifest':
            case 'putModFile':
              return { warnings: [], manifest_warnings: [] }
            case 'createMod':
            case 'importZIP':
              return { id: 'demo' }
            case 'pull':
              return { pulled: [] }
            case 'push':
              return { deployed: [] }
            case 'login':
            case 'loginWithCode':
            case 'register':
              return { ...apiResult, access_token: 'test-token', refresh_token: 'test-refresh' }
            default:
              return { ...apiResult }
          }
        }),
    },
  ),
  setTokens: vi.fn(),
}))

beforeEach(() => {
  apiMockState.reject = false
  apiMockState.responses = {}
  apiMockState.calls = []
})

const cases = [
  ['app', App, '/'],
  ['home', HomeView, '/'],
  ['AI store', AiStoreView, '/ai-store'],
  ['login', LoginView, '/login'],
  ['email login', LoginByEmailView, '/login-email'],
  ['register', RegisterView, '/register'],
  ['catalog detail', CatalogDetailView, '/catalog/1'],
  ['my store', MyStoreView, '/my-store'],
  ['wallet', WalletView, '/wallet'],
  ['payment plans', PaymentPlansView, '/plans'],
  ['workbench', WorkbenchView, '/workbench'],
  ['repository', RepositoryView, '/repository'],
  ['MOD authoring', ModAuthoringView, '/repository/mod/demo'],
  ['admin', AdminView, '/admin'],
  ['admin database', AdminDatabaseView, '/admin/database'],
  ['database viewer', DbViewerView, '/admin/database'],
  ['checkout', PaymentCheckoutView, '/checkout/order-1'],
  ['order detail', OrderDetailView, '/order/order-1'],
] as const

async function mountView(component: Component, path: string, namedRoutes = true) {
  const empty = { template: '<div />' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: namedRoutes ? [
      { path: '/login', name: 'login', component: empty },
      { path: '/checkout/:orderId', name: 'checkout', component: empty },
      { path: '/workbench/repository', name: 'workbench-repository', component: empty },
      { path: '/repository/mod/:modId', name: 'mod-authoring', component: empty },
      { path: '/:pathMatch(.*)*', component: empty },
    ] : [{ path: '/:pathMatch(.*)*', component: empty }],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = shallowMount(component, {
    global: {
      plugins: [createPinia(), router],
      stubs: {
        RouterLink: { template: '<a><slot /></a>' },
        RouterView: { template: '<div><slot /></div>' },
      },
    },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('application views', () => {
  it.each(cases)('mounts %s without a render failure', async (_name, component, path) => {
    localStorage.clear()
    const { wrapper } = await mountView(component, path, false)

    await flushPromises()
    expect(wrapper.exists()).toBe(true)

    const actions: Record<string, unknown[]> = {
      flash: ['done', true],
      formatTime: ['2026-08-17T00:00:00Z'],
      formatDate: ['2026-08-17T00:00:00Z'],
      artifactLabel: ['workflow'],
      securityLabel: ['verified'],
      securityLevelClass: ['verified'],
      truncate: ['a long value', 4],
      loadFacets: [],
      loadItems: [],
      setIndustry: ['manufacturing'],
      setArtifact: ['workflow'],
      setSecurityLevel: ['verified'],
      applyFilters: [],
      resetFilters: [],
      routeId: [],
      doBuy: [],
      doDownload: [1],
      refreshLandingAuth: [],
      startCountdown: [],
      sendCode: [],
      resendCode: [],
      doLogin: [],
      normPath: ['/folder//file.txt'],
      goRepo: [],
      refreshSummary: [],
      reload: [],
      saveManifest: [],
      loadSelectedFile: [],
      onPathSelect: [],
      saveFile: [],
      loadStore: [],
      orderId: [],
      fetchOrder: [],
      pollOrder: [],
      statusText: ['paid'],
      handleBuy: [{ id: 'starter', price: 9.9 }],
      startCooldown: [1],
      doRegister: [],
      getBlurb: [{ description: 'description' }],
      viewMod: ['demo'],
      load: [],
      submitCreate: [],
      onImport: [
        {
          target: {
            files: [new File(['zip'], 'demo.zip', { type: 'application/zip' })],
            value: 'demo.zip',
          },
        },
      ],
      doPull: [],
      doPush: [],
      txnTypeLabel: ['recharge'],
      loadTransactions: [],
      startAlipayRecharge: [],
      checkHome: [],
      switchMode: ['client'],
      doLogout: [],
    }
    const vm = wrapper.vm as unknown as Record<string, (...args: unknown[]) => unknown>
    for (const [action, args] of Object.entries(actions)) {
      const callable = vm[action]
      if (typeof callable !== 'function') continue
      try {
        await callable(...args)
      } catch {
        // Invalid/empty form state intentionally exercises each component's
        // validation or error branch; the mounted view must remain usable.
      }
    }

    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })

  it.each(cases)('keeps %s renderable when its API is unavailable', async (_name, component, path) => {
    apiMockState.reject = true
    localStorage.setItem('modstore_token', 'test-token')
    const consoleError = _name === 'database viewer' ? vi.spyOn(console, 'error').mockImplementation(() => undefined) : null
    const { wrapper } = await mountView(component, path, false)
    await flushPromises()

    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
    consoleError?.mockRestore()
  })

  it('covers payment plan checkout decisions', async () => {
    apiMockState.responses = {
      paymentPlans: {
        plans: [{ id: 9, name: 'Pro', price: 99, description: 'Pro plan', features: ['AI'] }],
      },
    }
    localStorage.clear()
    const { wrapper, router } = await mountView(PaymentPlansView, '/plans')
    const vm = wrapper.vm as unknown as Record<string, any>
    const plan = { id: 9 }

    await vm.handleBuy(plan)
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('login')

    localStorage.setItem('modstore_token', 'token')
    apiMockState.responses.paymentCheckout = { ok: false }
    await vm.handleBuy(plan)
    expect(vm.errorMsg).toBe('下单失败')

    apiMockState.responses.paymentCheckout = { ok: true, type: 'precreate', order_id: 'order-9' }
    await vm.handleBuy(plan)
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/checkout/order-9')

    apiMockState.responses.paymentCheckout = { ok: true, type: 'unknown' }
    await vm.handleBuy(plan)
    expect(vm.errorMsg).toBe('未知的支付类型')

    apiMockState.responses.paymentCheckout = new Error('checkout failed')
    await vm.handleBuy(plan)
    expect(vm.errorMsg).toContain('checkout failed')
    wrapper.unmount()
  })

  it('covers wallet validation and checkout decisions', async () => {
    apiMockState.responses = { balance: { balance: 10 }, transactions: { transactions: [] } }
    localStorage.clear()
    const { wrapper, router } = await mountView(WalletView, '/wallet')
    const vm = wrapper.vm as unknown as Record<string, any>

    await vm.startAlipayRecharge()
    expect(router.currentRoute.value.name).toBe('login')

    localStorage.setItem('modstore_token', 'token')
    vm.payAmount = 0
    await vm.startAlipayRecharge()
    expect(vm.payErr).toContain('大于 0')

    vm.payAmount = 10
    apiMockState.responses.paymentCheckout = { ok: false }
    await vm.startAlipayRecharge()
    expect(vm.payErr).toBe('下单失败')

    apiMockState.responses.paymentCheckout = { ok: true, type: 'page' }
    await vm.startAlipayRecharge()
    expect(vm.payErr).toContain('跳转地址')

    apiMockState.responses.paymentCheckout = { ok: true, type: 'precreate', order_id: 'wallet-1' }
    await vm.startAlipayRecharge()
    expect(router.currentRoute.value.fullPath).toBe('/checkout/wallet-1')

    apiMockState.responses.paymentCheckout = { ok: true, type: 'other' }
    await vm.startAlipayRecharge()
    expect(vm.payErr).toContain('未知')

    apiMockState.responses.paymentCheckout = new Error('network down')
    await vm.startAlipayRecharge()
    expect(vm.payErr).toContain('network down')
    expect(vm.txnTypeLabel('recharge')).toBe('管理员充值')
    expect(vm.txnTypeLabel('custom')).toBe('custom')
    expect(vm.txnTypeLabel('')).toBe('—')
    expect(vm.formatDate(null)).toBe('')
    expect(vm.formatDate('2026-08-17T00:00:00Z')).not.toBe('')
    wrapper.unmount()
  })

  it('covers catalog purchase and download outcomes', async () => {
    apiMockState.responses = {
      catalogDetail: {
        id: 1,
        name: 'Paid MOD',
        pkg_id: 'paid.mod',
        version: '1.0',
        artifact: 'workflow',
        price: 12.5,
        purchased: false,
      },
      buyItem: { message: 'bought' },
      downloadItem: {},
    }
    localStorage.setItem('modstore_token', 'token')
    vi.stubGlobal('alert', vi.fn())
    const { wrapper } = await mountView(CatalogDetailView, '/catalog/1')
    const vm = wrapper.vm as unknown as Record<string, any>
    await vm.doBuy()
    await vm.doDownload()
    expect(alert).toHaveBeenCalledWith('bought')

    apiMockState.responses.buyItem = new Error('buy failed')
    apiMockState.responses.downloadItem = new Error('download failed')
    await vm.doBuy()
    await vm.doDownload()
    expect(alert).toHaveBeenCalledWith('buy failed')
    expect(alert).toHaveBeenCalledWith('download failed')
    wrapper.unmount()
    vi.unstubAllGlobals()
  })

  it('covers repository formatting and synchronization alternatives', async () => {
    apiMockState.responses = {
      listMods: { data: [{ id: 'demo' }] },
      createMod: { id: 'created' },
      importZIP: { id: 'imported' },
      pull: { pulled: ['one'] },
      push: { deployed: ['two'] },
    }
    const { wrapper } = await mountView(RepositoryView, '/workbench/repository')
    const vm = wrapper.vm as unknown as Record<string, any>
    expect(vm.getBlurb(null)).toBe('')
    expect(vm.getBlurb({ library_blurb: ' library ' })).toBe('library')
    expect(vm.getBlurb({ description: '' })).toBe('')
    expect(vm.getBlurb({ description: 'x'.repeat(130) })).toHaveLength(118)
    await vm.submitCreate()
    await vm.onImport({ target: { files: [], value: 'empty' } })
    await vm.onImport({ target: { files: [new File(['zip'], 'demo.zip')], value: 'demo' } })
    await vm.doPull()
    await vm.doPush()

    for (const method of ['createMod', 'importZIP', 'pull', 'push']) {
      apiMockState.responses[method] = new Error(`${method} failed`)
    }
    await vm.submitCreate()
    await vm.onImport({ target: { files: [new File(['zip'], 'bad.zip')], value: 'bad' } })
    await vm.doPull()
    await vm.doPush()
    wrapper.unmount()
  })

  it('covers MOD authoring validation, save, and file branches', async () => {
    apiMockState.responses = {
      getMod: {
        manifest: { artifact: 'employee_pack', backend: { entry: 'main.py' } },
        files: ['manifest.json', 'backend/__init__.py', 'backend/main.py'],
      },
      getModAuthoringSummary: { warnings: [] },
      putModManifest: { warnings: ['warning'] },
      getModFile: { content: 'hello' },
      putModFile: { manifest_warnings: ['warning'] },
    }
    const { wrapper } = await mountView(ModAuthoringView, '/repository/mod/demo')
    const vm = wrapper.vm as unknown as Record<string, any>
    expect(vm.normPath('\\folder\\file')).toBe('folder/file')
    vm.manifestText = '{bad json'
    await vm.saveManifest()
    expect(vm.message).toContain('JSON')

    vm.manifestText = '{"name":"Demo"}'
    await vm.saveManifest()
    vm.selectedPath = 'backend/main.py'
    await vm.loadSelectedFile()
    expect(vm.fileContent).toBe('hello')
    await vm.saveFile()
    vm.onPathSelect()
    expect(vm.fileContent).toBe('')

    apiMockState.responses.putModManifest = new Error('manifest failed')
    apiMockState.responses.getModFile = new Error('read failed')
    apiMockState.responses.putModFile = new Error('write failed')
    await vm.saveManifest()
    vm.selectedPath = 'backend/main.py'
    await vm.loadSelectedFile()
    await vm.saveFile()
    vm.selectedPath = ''
    await vm.loadSelectedFile()
    await vm.saveFile()
    await nextTick()
    wrapper.unmount()
  })
})


describe('customer and administrator UI boundaries', () => {
  it.each([[false, false], [true, false], [true, true]])('navigation follows authenticated=%s/admin=%s and logout clears identity', async (loggedIn, admin) => {
    apiMockState.responses = { me: { id: 1, username: 'alice', is_admin: admin }, balance: { balance: 12.5 } }
    localStorage.clear()
    if (loggedIn) localStorage.setItem('modstore_token', 'token')
    const { wrapper, router } = await mountView(App, '/wallet')
    expect(wrapper.find('.btn-logout').exists()).toBe(loggedIn)
    expect(wrapper.findAll('.mode-tab')).toHaveLength(admin ? 2 : 0)
    if (loggedIn) {
      expect(wrapper.text()).toContain('¥12.50')
      if (admin) {
        await wrapper.findAll('.mode-tab')[1]!.trigger('click')
        await flushPromises()
        expect(router.currentRoute.value.path).toBe('/admin/database')
        expect(wrapper.text()).toContain('管理员模式')
        await wrapper.findAll('.mode-tab')[0]!.trigger('click')
        await flushPromises()
        expect(router.currentRoute.value.path).toBe('/')
        await router.push('/wallet')
        await flushPromises()
      }
      await wrapper.find('.btn-logout').trigger('click')
      await flushPromises()
      expect(localStorage.getItem('modstore_token')).toBeNull()
      expect(router.currentRoute.value.path).toBe('/')
      expect(wrapper.find('.navbar').exists()).toBe(false)
    } else {
      expect(wrapper.text()).toContain('登录')
      expect(wrapper.text()).not.toContain('¥12.50')
    }
    wrapper.unmount()
  })

  it('does not request administrative data for a customer account', async () => {
    apiMockState.responses = { me: { id: 29, is_admin: false } }
    const { wrapper } = await mountView(AdminDatabaseView, '/admin/database')
    expect(wrapper.text()).toContain('需要管理员权限')
    expect(apiMockState.calls.some(([name]) => String(name).startsWith('adminList'))).toBe(false)
    wrapper.unmount()
  })

  it.each([AdminDatabaseView, DbViewerView])('renders populated ledgers without dropping negative balances or escaping status', async (component) => {
    const users = [{ id: 1, username: '<script>admin</script>', email: '', is_admin: true }, { id: 2, username: 'customer', email: 'a@example.com', is_admin: false, created_at: '2026-10-07T00:00:00Z' }]
    const wallets = [{ id: 1, user_id: 1, balance: 12.5 }, { id: 2, user_id: 2, balance: -5, updated_at: '2026-10-07T00:00:00Z' }]
    const catalog = [{ id: 1, name: 'Free MOD', pkg_id: 'free', price: 0 }, { id: 2, name: 'Paid MOD', pkg_id: 'paid', price: 12.5, downloads: 3, created_at: '2026-10-07T00:00:00Z' }]
    const transactions = [{ id: 1, user_id: 1, amount: 12.5, status: 'completed', description: '' }, { id: 2, user_id: 2, amount: -5, status: 'pending', description: 'refund', created_at: '2026-10-07T00:00:00Z' }]
    apiMockState.responses = { me: { is_admin: true }, adminListUsers: { users, items: users }, adminListWallets: { items: wallets }, adminListCatalog: { items: catalog }, adminListTransactions: { items: transactions } }
    const { wrapper } = await mountView(component, '/admin/database')
    expect(wrapper.findAll('tbody tr')).toHaveLength(8)
    expect(wrapper.text()).toContain('¥-5.00')
    expect(wrapper.text()).toContain('¥12.50')
    expect(wrapper.text()).toContain('免费')
    expect(wrapper.text()).toContain('pending')
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.text()).toContain('<script>admin</script>')
    expect(wrapper.findAll('.db-empty')).toHaveLength(0)
    wrapper.unmount()
  })

  it('keeps catalog filters, ownership and errors consistent with visible results', async () => {
    apiMockState.responses = {
      catalogFacets: { industries: ['manufacturing'], artifacts: ['mod', 'employee_pack', 'bundle', 'surface', 'unknown'] },
      catalog: { items: ['personal', 'enterprise', 'confidential', 'unknown'].map((security_level, index) => ({ id: index + 1, name: `Item ${index}`, pkg_id: `pkg.${index}`, version: '1', artifact: ['mod', 'employee_pack', 'bundle', 'unknown'][index], industry: index ? 'manufacturing' : '', description: index ? 'x'.repeat(130) : '', security_level, purchased: index === 1, price: index ? 12.5 : 0 })), total: 9 },
    }
    const { wrapper } = await mountView(AiStoreView, '/ai-store')
    expect(wrapper.findAll('.store-card')).toHaveLength(4)
    expect(wrapper.text()).toContain('已购')
    expect(wrapper.text()).toContain('免费')
    expect(wrapper.text()).toContain('共 9 条')
    const button = (text: string) => wrapper.findAll('button').find(b => b.text() === text)!
    await button('manufacturing').trigger('click')
    await button('AI 员工包').trigger('click')
    await button('保密级').trigger('click')
    await wrapper.find('#store-search').setValue('  inventory  ')
    await wrapper.find('#store-search').trigger('keydown.enter')
    await flushPromises()
    expect(apiMockState.calls.filter(([name]) => name === 'catalog').at(-1)).toEqual(['catalog', 'inventory', 'employee_pack', 80, 0, 'manufacturing', 'confidential'])
    await button('重置').trigger('click')
    await flushPromises()
    expect(apiMockState.calls.filter(([name]) => name === 'catalog').at(-1)).toEqual(['catalog', '', '', 80, 0, '', ''])
    apiMockState.responses.catalog = new Error('catalog unavailable')
    await button('搜索').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('catalog unavailable')
    expect(wrapper.findAll('.store-card')).toHaveLength(0)
    wrapper.unmount()
  })
})
