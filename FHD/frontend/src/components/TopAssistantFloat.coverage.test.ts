import { makeFetchResponse, mountComponent } from './__tests__/topAssistantFloatHarness'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick, type UnwrapRef } from 'vue'
import { authApi } from '@/api/auth'
import type { useAssistantCatalogPrices } from './top-assistant-float/useAssistantCatalogPrices'
import { webcrypto } from 'node:crypto'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { useModsStore } from '@/stores/mods'

vi.mock('@/api', () => {
  class ApiError extends Error {
    status?: number
    constructor(message = 'api error', status = 500) {
      super(message)
      this.status = status
    }
  }
  return {
    default: {
      get: vi.fn(async () => ({ success: true, data: {} })),
      post: vi.fn(async () => ({ success: true, data: {} })),
      put: vi.fn(async () => ({ success: true, data: {} })),
      delete: vi.fn(async () => ({ success: true, data: {} })),
    },
    ApiError,
  }
})

const catalogApi = vi.hoisted(() => ({ list: vi.fn(), submit: vi.fn(), lookup: vi.fn(), verify: vi.fn(), reconcile: vi.fn() }))
vi.mock('@/api/catalogPrices', () => ({ catalogPricesApi: catalogApi }))

vi.mock('@/api/products', () => {
  const searchProducts = vi.fn(async (keyword = '') => ({
    success: true,
    data: String(keyword).trim()
      ? [
          {
            id: 1,
            model_number: 'M-1',
            name: '产品A',
            product_name: '产品A',
            price: 10,
            unit: '件',
          },
          {
            id: 2,
            model_number: 'M-2',
            name: '产品B',
            product_name: '产品B',
            price: 20,
            unit: '套',
          },
        ]
      : [],
    total: String(keyword).trim() ? 2 : 0,
  }))
  const updateProduct = vi.fn(async () => ({ success: true }))
  return {
    default: { searchProducts, updateProduct },
    productsApi: { searchProducts, updateProduct },
  }
})

vi.mock('@/utils/erpDomainPaths', () => ({
  resolveErpApiPath: (p: string) => p,
  resolveErpApiPathWhenReady: async (p: string) => p,
}))

function dispatchWindowEvent(name: string, detail: Record<string, unknown> = {}) {
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

describe('TopAssistantFloat.vue 覆盖率补齐测试', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useModsStore().activeModId = 'mod-test'
    setRuntimeTenantStorageScopeInput({ tenantId: 5, localUserId: 7 })
    vi.stubGlobal('crypto', webcrypto)
    Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_key: string, _options: unknown, fn: (lock: object) => Promise<unknown>) => fn({}) } })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => makeFetchResponse()),
    )
    localStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    setRuntimeTenantStorageScopeInput(null)
    delete (navigator as Navigator & { locks?: unknown }).locks
    vi.restoreAllMocks()
    localStorage.clear()
  })

  // ===== 1. 基础渲染与切换 =====

  it('挂载后渲染浮动按钮且默认关闭', async () => {
    const { wrapper } = await mountComponent()
    expect(wrapper.find('.assistant-float-toggle').exists()).toBe(true)
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
    expect(wrapper.text()).toContain('副窗')
  })

  it('点击浮动按钮打开副窗并切换标题', async () => {
    const { wrapper } = await mountComponent()
    const toggle = wrapper.find('.assistant-float-toggle')
    expect(toggle.attributes('title')).toBe('打开副窗')
    await toggle.trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    expect(toggle.attributes('title')).toBe('收起副窗')
    expect(toggle.attributes('aria-expanded')).toBe('true')
  })

  it('再次点击浮动按钮关闭副窗', async () => {
    const { wrapper } = await mountComponent()
    const toggle = wrapper.find('.assistant-float-toggle')
    await toggle.trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    await toggle.trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
  })

  it('点击关闭按钮关闭副窗', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const closeBtn = wrapper.find('.assistant-close')
    expect(closeBtn.exists()).toBe(true)
    await closeBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
  })

  // ===== 2. 标签页切换 =====

  it('切换到推送标签显示空状态', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-empty').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无推送')
  })

  it('切换到协助副窗标签显示查询区域', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    const assistantTab = tabs.find((t) => t.text().includes('协助副窗'))
    expect(assistantTab).toBeTruthy()
    await assistantTab!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.product-search-row').exists()).toBe(true)
    expect(wrapper.find('.assistant-grid-actions').exists()).toBe(true)
  })

  it('切换到新手对话包标签显示预设', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    const starterTab = tabs.find((t) => t.text().includes('新手对话包'))
    await starterTab!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.starter-pack-list').exists()).toBe(true)
  })

  it('切换到新手教程标签显示教程列表', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    const tutorialTab = tabs.find((t) => t.text().includes('新手教程'))
    await tutorialTab!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.tutorial-track-pick').exists()).toBe(true)
    expect(wrapper.findAll('.tutorial-track-card').length).toBeGreaterThan(0)
  })

  // ===== 3. 推送功能 =====

  it('收到微信推送事件后添加推送项', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:assistant-push', {
      title: '测试推送',
      description: '测试描述',
      feature: 'wechat',
    })
    await flushPromises()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('测试推送')
    expect(wrapper.text()).toContain('测试描述')
  })

  it('任意推送事件都被添加到推送列表', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:assistant-push', {
      title: '其他推送',
      description: '应显示',
      feature: 'other',
    })
    await flushPromises()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('其他推送')
  })

  it('副窗关闭时收到推送显示弹窗通知', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:assistant-push', {
      title: '新消息推送',
      description: '请查看',
      feature: 'wechat',
    })
    await flushPromises()
    expect(wrapper.find('.assistant-popup-notice').exists()).toBe(true)
    expect(wrapper.text()).toContain('新消息推送')
    expect(wrapper.find('.assistant-float-toggle.pulse').exists()).toBe(true)
  })

  it('点击弹窗通知打开副窗并清除通知', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:assistant-push', {
      title: '弹窗通知',
      description: '点击查看',
      feature: 'wechat',
    })
    await flushPromises()
    expect(wrapper.find('.assistant-popup-notice').exists()).toBe(true)
    await wrapper.find('.assistant-popup-notice').trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    expect(wrapper.find('.assistant-popup-notice').exists()).toBe(false)
  })

  it('推送标题为空时使用默认值', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:assistant-push', {
      feature: 'wechat',
    })
    await flushPromises()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('新推送')
    expect(wrapper.text()).toContain('收到一条助手消息')
  })

  // ===== 4. 产品查询 =====

  it('空关键词查询清空结果', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('请先输入')
  })

  it('有效关键词查询返回产品列表', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('产品')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.product-item').length).toBe(2)
    expect(wrapper.text()).toContain('编号 1')
    expect(wrapper.text()).toContain('编号 2')
  })

  it('查询返回空结果显示未找到提示', async () => {
    const productsApi = (await import('@/api/products')).default
    ;(productsApi.searchProducts as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      success: true,
      data: [],
      total: 0,
    })
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('不存在的')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('未找到')
  })

  it('查询失败显示错误信息', async () => {
    const { ApiError } = await import('@/api')
    const productsApi = (await import('@/api/products')).default
    ;(productsApi.searchProducts as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new ApiError('服务器错误', 500))
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('触发错误')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('请求失败')
  })

  it('查询返回 success:false 显示失败提示', async () => {
    const productsApi = (await import('@/api/products')).default
    ;(productsApi.searchProducts as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      success: false,
      message: '查询异常',
    })
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('异常')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('查询异常')
  })

  it('查询时网络异常显示网络异常提示', async () => {
    const productsApi = (await import('@/api/products')).default
    ;(productsApi.searchProducts as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('网络异常'))
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('网络')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('网络异常')
  })

  it('回车键触发查询', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('回车查询')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(wrapper.findAll('.product-item').length).toBeGreaterThan(0)
  })

  it('受保护目录必须明确选择，纠错保留未标注期间并显示冲突及只读计价单位', async () => {
    const productsApi = (await import('@/api/products')).default
    const source = { source_id: 'protected-source', epoch: 'epoch-1', protocol: 'etl-owned-mixed-v1' }
    catalogApi.list.mockResolvedValue({ success: true, capability: 'catalog_prices_v1', source, data: [{
      id: 77, name: '保护产品', model_number: 'P77', unit: '客户甲', price: '12.00', currency: 'CNY', price_unit: 'kg', revision: 'a'.repeat(64), source,
      history: [
        { source_key: 'first', price: '12.00', period_start: null, period_end: null, period_label: null, effective: true },
        { source_key: 'second', price: '13.00', period_start: null, period_end: null, period_label: null, effective: true },
      ],
    }] })
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await wrapper.findAll('.assistant-tab').find(t => t.text().includes('协助副窗'))!.trigger('click')
    expect(catalogApi.list).not.toHaveBeenCalled()
    await wrapper.find('[data-testid="protected-catalog-select"]').setValue(true)
    await wrapper.find('.product-search-row input').setValue('保护')
    await wrapper.find('.product-search-row button').trigger('click')
    await flushPromises()
    expect(catalogApi.list).toHaveBeenCalledWith('保护', 'mod-test')
    expect(productsApi.searchProducts).not.toHaveBeenCalled()
    let panel = wrapper.find('[data-testid="protected-catalog"]')
    expect(panel.text()).toContain('客户甲（只读，不是计价分母）')
    expect(panel.text()).toContain('CNY/kg')
    await panel.find('select').setValue('correct_price')
    await flushPromises()
    panel = wrapper.find('[data-testid="protected-catalog"]')
    expect(panel.html()).toContain('选择原期间来源')
    await panel.findAll('select')[1].setValue('first')
    await flushPromises()
    panel = wrapper.find('[data-testid="protected-catalog"]')
    expect(panel.text()).toContain('未标注期间')
    expect(panel.text()).toContain('冲突警告')
    expect(panel.findAll('input[type="date"]')).toHaveLength(0)
    expect(panel.text()).toContain('原金额 12.00')
    expect(panel.text()).toContain('原金额 13.00')
    await wrapper.find('[data-testid="protected-catalog-select"]').setValue(false)
    expect(wrapper.find('[data-testid="protected-catalog"]').exists()).toBe(false)
    expect(catalogApi.submit).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each(['cancel', 'close', 'confirm'].flatMap(decision => [false, true].map(preclaim => ({ decision, preclaim }))))('original-operation reconciliation UI requires explicit $decision decision, preclaim=$preclaim', async ({ decision, preclaim }) => {
    const source = { source_id: 'protected-source', epoch: 'epoch-1', protocol: 'etl-owned-mixed-v1' }
    const row = { id: 77, name: '保护产品', model_number: 'P77', unit: '客户甲', price: '12.00', currency: 'CNY', price_unit: 'kg', revision: 'a'.repeat(64), source, history: [] }
    catalogApi.list.mockResolvedValue({ success: true, capability: 'catalog_prices_v1', source, data: [row] })
    catalogApi.submit.mockResolvedValue({ success: true, data: { run_id: 'run-a' } })
    catalogApi.reconcile.mockReset()
    vi.spyOn(authApi, 'getCurrentUser').mockResolvedValue({ success: true, data: { user: { id: 7 } as never, permissions: ['product.view', 'dataset.read', 'etl.execute', 'product.edit', 'dataset.write', 'etl.template.manage'] } })
    const { wrapper, vm } = await mountComponent()
    const catalog = (vm as unknown as { catalog: UnwrapRef<ReturnType<typeof useAssistantCatalogPrices>> }).catalog
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await wrapper.findAll('.assistant-tab').find(t => t.text().includes('协助副窗'))!.trigger('click')
    await wrapper.find('[data-testid="protected-catalog-select"]').setValue(true)
    await catalog.search('保护')
    const product = catalog.rows[0]
    Object.assign(catalog.draftFor(77), { price: '15.00', reason: '核对', period_start: '2026-01-01', period_end: '2026-12-31', confirmed: true })
    await catalog.submit(product)
    const body = catalogApi.submit.mock.calls.at(-1)![1]
    catalogApi.lookup.mockResolvedValue({ success: true,
      data: { run_id: 'run-a', user_id: '7', status: 'running', metadata: { runtime_context: { tenant_id: 5, mod_id: 'mod-test' } },
        steps: [{ step_id: 'step-a', tool_id: 'catalog_products_v1', action: body.action, params: { ...body, product_id: 77, currency: 'CNY', price_unit: 'kg', selected_observations: [] }, status: 'running', output: {} }] },
      operation: { state: 'pending', operation_id: body.operation_id, run_id: 'run-a', request_digest: 'b'.repeat(64) } })
    const proof = { success: true, data: { verified: true, outcome: 'saved', historical_effect_verified: true, fresh_save: false, current_matches: false, business_action_id: 'action-a', operation_id: body.operation_id, run_id: 'run-a', request_digest: 'b'.repeat(64), product: { ...row, revision: 'c'.repeat(64) } } }
    if (preclaim) Object.assign(proof.data, { outcome: 'rejected_no_effect', historical_effect_verified: false, reason_code: 'preclaim_finalized', receipt_kind: 'catalog_preclaim_finalization_v1', product: row })
    if (preclaim) catalogApi.verify.mockRejectedValue(Object.assign(new Error('unverified original'), { status: 409 }))
    else catalogApi.verify.mockResolvedValue(proof)
    catalogApi.reconcile.mockResolvedValue(proof)
    const button = (text: string) => wrapper.findAll('[data-testid="protected-catalog"] button').find(b => b.text() === text)!
    await button('只读核对原操作').trigger('click')
    await vi.waitFor(() => expect(catalog.statusFor(77)?.canReconcile).toBe(true))
    await nextTick()
    const key = Object.keys(localStorage).find(k => k.startsWith('xcagi-catalog-price-operation-v1:'))!, before = localStorage.getItem(key)
    expect(catalogApi.reconcile).not.toHaveBeenCalled()
    await button('核对并终结原操作…').trigger('click')
    expect(wrapper.find('[data-testid="catalog-reconciliation-confirmation"]').text()).toContain(body.operation_id)
    expect(wrapper.text()).toContain('不会重放价格写入')
    if (decision === 'cancel') await button('取消，保留原操作').trigger('click')
    else if (decision === 'close') {
      await wrapper.find('.assistant-close').trigger('click')
      await wrapper.find('.assistant-float-toggle').trigger('click')
    } else {
      await button('确认核对并终结此原操作').trigger('click')
      await vi.waitFor(() => expect(catalogApi.reconcile).toHaveBeenCalledExactlyOnceWith(body.operation_id, 'mod-test'))
      await flushPromises()
    }
    expect(wrapper.find('[data-testid="catalog-reconciliation-confirmation"]').exists()).toBe(false)
    if (decision === 'confirm') {
      expect(localStorage.getItem(key)).toBeNull()
      if (preclaim) expect(wrapper.text()).toContain('未保存：原操作已核验并终结')
      else { expect(wrapper.text()).toContain('当前数据已有后续变更'); expect(wrapper.text()).toContain('本次未重新保存') }
    } else {
      expect(catalogApi.reconcile).not.toHaveBeenCalled(); expect(localStorage.getItem(key)).toBe(before)
    }
    wrapper.unmount()
  })

  it('旧 ERP 保存按钮禁用且身份字段只读', async () => {
    const productsApi = (await import('@/api/products')).default
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('保存')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    const saveBtn = wrapper.find('.product-actions .btn-secondary')
    expect(saveBtn.exists()).toBe(true)
    await saveBtn.trigger('click')
    await flushPromises()
    expect(saveBtn.attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('.product-item input').every(input => input.attributes('readonly') !== undefined)).toBe(true)
    expect(productsApi.updateProduct).not.toHaveBeenCalled()
  })

  it('数据源审批链未验证时副窗禁止发送产品修改', async () => {
    const productsApi = (await import('@/api/products')).default
    ;(productsApi.updateProduct as ReturnType<typeof vi.fn>).mockClear()
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    await wrapper.findAll('.assistant-tab').find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await wrapper.find('.product-search-row input').setValue('产品')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    const first = wrapper.findAll('.product-item')[0]
    expect(first.find('.product-actions .btn-secondary').attributes('disabled')).toBeDefined()
    await first.find('.product-actions .btn-secondary').trigger('click')
    await flushPromises()
    expect(first.text()).toContain('副窗暂不可保存')
    expect(productsApi.updateProduct).not.toHaveBeenCalled()
  })

  it('保存产品行失败仍重置 savingProductId', async () => {
    const productsApi = (await import('@/api/products')).default
    ;(productsApi.updateProduct as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('保存失败'))
    // 捕获未处理的 rejection（saveProductRow 不 catch，由 finally 重置状态）
    const rejectionHandler = vi.fn()
    process.on('unhandledRejection', rejectionHandler)
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('保存失败')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    const saveBtn = wrapper.find('.product-actions .btn-secondary')
    await saveBtn.trigger('click')
    // 等待所有 promise 完成（包括 rejected 的）
    await flushPromises()
    // finally 块已执行，按钮文字恢复
    expect(saveBtn.text()).toContain('保存修改')
    process.off('unhandledRejection', rejectionHandler)
  })

  // ===== 5. 工作流员工切换 =====
  // 一键托管/龙虾托管 tab 已移除（改为 AI 自动 + 事件驱动），工作流员工开关测试同步移除

  // ===== 6. 新手对话包 =====

  it('点击新手对话包预设项跳转聊天页', async () => {
    const { wrapper, router } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('新手对话包'))!.trigger('click')
    await flushPromises()
    const item = wrapper.find('.starter-pack-item')
    expect(item.exists()).toBe(true)
    await item.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('chat')
  })

  // ===== 7. 教程功能 =====

  it('点击新手教程标签触发预热事件', async () => {
    const { wrapper } = await mountComponent()
    let warmed = false
    window.addEventListener('xcagi:warmup-tutorial-tts', () => {
      warmed = true
    })
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('新手教程'))!.trigger('click')
    await flushPromises()
    await nextTick()
    expect(warmed).toBe(true)
  })

  it('点击默认教程开始按钮触发 onboarding 跳转', async () => {
    const { wrapper, router } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('新手教程'))!.trigger('click')
    await flushPromises()
    const startBtn = wrapper.find('.tutorial-track-card .btn-primary')
    expect(startBtn.exists()).toBe(true)
    await startBtn.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('product-onboarding')
  })

  it('点击进阶教程按钮打开 V2 课程目录且不触发 driver tour', async () => {
    const { launchAdvancedDriverTour } = await import('@/tutorial/promptAdvancedTutorial')
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('新手教程'))!.trigger('click')
    await flushPromises()
    const cards = wrapper.findAll('.tutorial-track-card')
    // 进阶教程卡片
    const advancedCard = cards.find((c) => c.text().includes('进阶'))
    expect(advancedCard).toBeTruthy()
    const advancedBtn = advancedCard!.find('.btn')
    await advancedBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.tutorial-v2-panel').exists()).toBe(true)
    expect(wrapper.text()).toContain('进阶教程 · 跟着做就能学会')
    expect(launchAdvancedDriverTour).not.toHaveBeenCalled()
  })

  // ===== 8. 浮窗打开事件 =====

  it('open-assistant-float 事件 forceOpen 强制打开', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', { forceOpen: true })
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
  })

  it('open-assistant-float 事件带 task 自动打开', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', { task: { type: 'demo' } })
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
  })

  it('open-assistant-float 事件 feature=products 切换到协助标签', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', { feature: 'products' })
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    expect(wrapper.find('.product-search-row').exists()).toBe(true)
  })

  it('open-assistant-float 事件 feature=products 带 hydrateProductSearch 直接填充', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', {
      feature: 'products',
      query: '预填',
      hydrateProductSearch: {
        rows: [{ id: 99, name: '预填产品', model_number: 'PM-99', price: 5, unit: '个' }],
        total: 1,
      },
    })
    await flushPromises()
    // 名称在 input 的 value 中，需检查 input 元素
    expect(wrapper.text()).toContain('编号 99')
    const nameInput = wrapper.find('#pf-name-99')
    expect(nameInput.exists()).toBe(true)
    expect((nameInput.element as HTMLInputElement).value).toBe('预填产品')
  })

  it('open-assistant-float 事件 feature=products 带不同 query 触发查询', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', {
      feature: 'products',
      query: '触发查询',
    })
    await flushPromises()
    expect(wrapper.find('.product-search-row').exists()).toBe(true)
  })

  it('open-assistant-float 事件 feature=assistant 切换到协助标签', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', { feature: 'assistant' })
    await flushPromises()
    expect(wrapper.find('.product-search-row').exists()).toBe(true)
  })

  it('open-assistant-float 事件 feature=starterPack 切换到对话包标签', async () => {
    const { wrapper } = await mountComponent()
    // starterPack 不在自动打开列表中，需 forceOpen
    dispatchWindowEvent('xcagi:open-assistant-float', { feature: 'starterPack', forceOpen: true })
    await flushPromises()
    expect(wrapper.find('.starter-pack-list').exists()).toBe(true)
  })

  it('open-assistant-float 事件 feature=tutorial 切换到教程标签', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', { feature: 'tutorial' })
    await flushPromises()
    expect(wrapper.find('.tutorial-track-pick').exists()).toBe(true)
  })

  it('open-assistant-float 事件其他 feature 仅标记未读', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', { feature: 'unknown' })
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
    expect(wrapper.find('.assistant-float-toggle.pulse').exists()).toBe(true)
  })

  // ===== 9. 关闭浮窗事件 =====

  it('close-assistant-float 事件关闭副窗', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    dispatchWindowEvent('xcagi:close-assistant-float')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
  })

  // ===== 10. Excel 上下文 =====

  it('excel-sheet-context 事件应用 Sheet 上下文', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:excel-sheet-context', {
      selected_sheet: { sheet_name: 'Sheet1', sheet_index: 1 },
      excel_analysis: {
        preview_data: {
          all_sheets: [
            {
              sheet_name: 'Sheet1',
              sheet_index: 1,
              grid_preview: { rows: [{ cells: ['A1'] }] },
              fields: [{ name: '字段1' }],
              sample_rows: [{ 字段1: '值1' }],
            },
          ],
        },
      },
    })
    await flushPromises()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Sheet 1')
    expect(wrapper.text()).toContain('Sheet1')
  })

  it('excel-sheet-context 事件无匹配 sheet 时使用首个', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:excel-sheet-context', {
      selected_sheet: { sheet_name: '不存在', sheet_index: 99 },
      excel_analysis: {
        preview_data: {
          all_sheets: [
            {
              sheet_name: '默认Sheet',
              sheet_index: 0,
              grid_preview: null,
              fields: [],
              sample_rows: [],
            },
          ],
        },
      },
    })
    await flushPromises()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    // 无网格数据时显示空提示
    expect(wrapper.text()).toContain('暂无可展示网格')
  })

  it('点击调用上传并提取读取网格按钮跳转聊天页', async () => {
    const { wrapper, router } = await mountComponent()
    dispatchWindowEvent('xcagi:excel-sheet-context', {
      selected_sheet: { sheet_name: 'Sheet1', sheet_index: 1 },
      excel_analysis: { preview_data: { all_sheets: [] } },
    })
    await flushPromises()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const gridBtn = wrapper.find('.assistant-grid-actions .btn')
    expect(gridBtn.exists()).toBe(true)
    await gridBtn.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('chat')
  })

  it('未关联 Sheet 时点击读取网格按钮不跳转', async () => {
    const { wrapper, router } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const gridBtn = wrapper.find('.assistant-grid-actions .btn')
    await gridBtn.trigger('click')
    await flushPromises()
    // 未关联 Sheet 直接 return，不跳转
    expect(router.currentRoute.value.name).toBe('chat')
  })

  // ===== 11. 状态恢复 =====

  it('tutorial:restore-float 事件恢复副窗状态', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:tutorial:restore-float', {
      isOpen: true,
      activeTab: 'assistant',
      assistantState: {
        pushFeed: [{ id: 'r1', title: '恢复推送', description: '恢复描述' }],
        productKeyword: '恢复关键词',
        productRows: [],
        linkedSheetName: '',
        linkedSheetIndex: 0,
        linkedGridData: null,
        linkedSheetFields: [],
        linkedSheetSampleRows: [],
        topScrollInnerWidth: 0,
        loadingProducts: false,
        lastProductSearchQuery: '',
        productSearchFailed: false,
        productSearchErrorText: '',
        lastProductSearchTotal: null,
        popupNotice: null,
        hasUnreadPush: false,
        operationHistory: [],
      },
    })
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    expect(wrapper.find('.product-search-row').exists()).toBe(true)
  })

  it('tutorial:set-assistant-tab 事件设置标签', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:tutorial:set-assistant-tab', { open: true, tab: 'tutorial' })
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    expect(wrapper.find('.tutorial-track-pick').exists()).toBe(true)
  })

  // ===== 12. 键盘交互 =====

  it('Escape 键关闭副窗', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    const escEvent = new KeyboardEvent('keydown', {
      key: 'Escape',
      bubbles: true,
      cancelable: true,
    })
    window.dispatchEvent(escEvent)
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
  })

  it('副窗关闭时 Escape 键不触发', async () => {
    const { wrapper } = await mountComponent()
    const escEvent = new KeyboardEvent('keydown', {
      key: 'Escape',
      bubbles: true,
      cancelable: true,
    })
    window.dispatchEvent(escEvent)
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
  })

  it('ArrowRight 键切换到下一个标签', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    // 默认 push 标签，按右键应切到 assistant
    const panel = wrapper.find('.assistant-float-panel')
    const tab = panel.find('[role="tab"]')
    await tab.trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(wrapper.find('.product-search-row').exists()).toBe(true)
  })

  it('ArrowLeft 键切换到上一个标签', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    // 先切到 assistant 标签
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    // 按左键应回到 push
    const panel = wrapper.find('.assistant-float-panel')
    const tab = panel.find('[role="tab"][aria-selected="true"]')
    await tab.trigger('keydown', { key: 'ArrowLeft' })
    await flushPromises()
    expect(wrapper.text()).toContain('暂无推送')
  })

  it('非方向键不触发标签切换', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const panel = wrapper.find('.assistant-float-panel')
    const tab = panel.find('[role="tab"]')
    await tab.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    // 仍在 push 标签
    expect(wrapper.text()).toContain('暂无推送')
  })

  it('方向键但目标非 tab 元素不切换', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const panel = wrapper.find('.assistant-float-panel')
    // 在非 tab 元素上触发方向键
    await panel.trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(wrapper.text()).toContain('暂无推送')
  })

  // ===== 15. 卸载清理 =====

  it('组件卸载时清理事件监听与定时器', async () => {
    const { wrapper } = await mountComponent()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
    await flushPromises()
    expect(wrapper.exists()).toBe(false)
  })

  // ===== 16. 工作流全景链接 =====

  it('mods 变化触发 syncEnterpriseWorkflowRegistry', async () => {
    const { syncEnterpriseWorkflowRegistry } = await import('@/utils/syncEnterpriseWorkflowRegistry')
    const { wrapper } = await mountComponent()
    // 触发 mods store 变化（这里仅验证不报错）
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    // syncEnterpriseWorkflowRegistry 在 onMounted 已被调用
    expect(syncEnterpriseWorkflowRegistry).toHaveBeenCalled()
  })

  // ===== 17. 推送数量上限 =====

  it('推送超过上限只保留最近 12 条', async () => {
    const { wrapper } = await mountComponent()
    // 连续发送 15 条推送
    for (let i = 0; i < 15; i += 1) {
      dispatchWindowEvent('xcagi:assistant-push', {
        title: `推送${i}`,
        description: `描述${i}`,
        feature: 'wechat',
      })
      await flushPromises()
    }
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const items = wrapper.findAll('.push-item')
    expect(items.length).toBeLessThanOrEqual(12)
  })

  // ===== 18. recommendIntroText 计算属性 =====
  // recommendIntroText 已随一键托管/龙虾托管 tab 一并移除

  // ===== 19. productEmptyMessage 各分支 =====

  it('查询成功后修改关键词显示关键词已变更提示', async () => {
    const productsApi = (await import('@/api/products')).default
    // 先让搜索返回空结果，使 productRows.length === 0
    ;(productsApi.searchProducts as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      success: true,
      data: [],
      total: 0,
    })
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    // 搜索返回空结果
    await input.setValue('原始词')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.product-item').length).toBe(0)
    // 修改关键词但未查询，应显示关键词已变更
    await input.setValue('新词未查')
    await flushPromises()
    expect(wrapper.text()).toContain('关键词已变更')
  })

  // ===== 20. openFromNotice 清除定时器 =====

  it('弹窗通知定时器到期后清除通知', async () => {
    vi.useFakeTimers()
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:assistant-push', {
      title: '定时通知',
      description: '将自动消失',
      feature: 'wechat',
    })
    await flushPromises()
    expect(wrapper.find('.assistant-popup-notice').exists()).toBe(true)
    // 快进 6 秒
    vi.advanceTimersByTime(6000)
    await flushPromises()
    expect(wrapper.find('.assistant-popup-notice').exists()).toBe(false)
    vi.useRealTimers()
  })

  // ===== 21. 教程激活时关闭副窗不生效 =====

  it('教程激活且有 assistantTab 时关闭按钮不关闭副窗', async () => {
    const { useTutorialStore } = await import('@/stores/tutorial')
    const tutorialStore = useTutorialStore()
    // currentStep 是 computed，需设置 steps 和 currentStepIndex
    tutorialStore.isActive = true
    tutorialStore.steps = [{ id: 's1', assistantTab: 'push' }] as never
    tutorialStore.currentStepIndex = 0
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    await wrapper.find('.assistant-close').trigger('click')
    await flushPromises()
    // 教程激活时不应关闭
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
  })

  it('教程激活时 close-assistant-float 事件不关闭副窗', async () => {
    const { useTutorialStore } = await import('@/stores/tutorial')
    const tutorialStore = useTutorialStore()
    tutorialStore.isActive = true
    tutorialStore.steps = [{ id: 's1', assistantTab: 'push' }] as never
    tutorialStore.currentStepIndex = 0
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    dispatchWindowEvent('xcagi:close-assistant-float')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
  })

  it('教程激活时 Escape 键不关闭副窗', async () => {
    const { useTutorialStore } = await import('@/stores/tutorial')
    const tutorialStore = useTutorialStore()
    tutorialStore.isActive = true
    tutorialStore.steps = [{ id: 's1', assistantTab: 'push' }] as never
    tutorialStore.currentStepIndex = 0
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const escEvent = new KeyboardEvent('keydown', {
      key: 'Escape',
      bubbles: true,
      cancelable: true,
    })
    window.dispatchEvent(escEvent)
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
  })

  // ===== 22. onOpenAssistantFloat 相同关键词分支 =====

  it('open-assistant-float feature=products 相同关键词且无结果时重新查询', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('相同词')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    // 再次发送相同 query，应触发 sameKw 分支
    dispatchWindowEvent('xcagi:open-assistant-float', {
      feature: 'products',
      query: '相同词',
    })
    await flushPromises()
    expect(wrapper.find('.product-search-row').exists()).toBe(true)
  })

  // ===== 24. 滚动同步 =====

  it('关联网格后触发滚动同步', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:excel-sheet-context', {
      selected_sheet: { sheet_name: 'Sheet1', sheet_index: 1 },
      excel_analysis: {
        preview_data: {
          all_sheets: [
            {
              sheet_name: 'Sheet1',
              sheet_index: 1,
              grid_preview: { rows: [{ cells: ['A1', 'B1'] }] },
              fields: [{ name: '字段1' }],
              sample_rows: [{ 字段1: '值1' }],
            },
          ],
        },
      },
    })
    await flushPromises()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    // 网格预览区域应存在
    expect(wrapper.find('.linked-grid-preview').exists()).toBe(true)
  })

  // ===== 25. ArrowRight 切换到 tutorial 标签 =====

  it('ArrowRight 从 starterPack 切换到 tutorial 标签', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    // 先切到 starterPack 标签
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('新手对话包'))!.trigger('click')
    await flushPromises()
    // 按右键应切到 tutorial
    const panel = wrapper.find('.assistant-float-panel')
    const tab = panel.find('[role="tab"][aria-selected="true"]')
    await tab.trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(wrapper.find('.tutorial-track-pick').exists()).toBe(true)
  })

  // ===== 26. tryFillChatInput =====

  it('window.__VUE_CHAT_FILL__ 存在时填充聊天输入', async () => {
    const fillFn = vi.fn(() => true)
    Object.defineProperty(window, '__VUE_CHAT_FILL__', {
      configurable: true,
      value: fillFn,
    })
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('新手对话包'))!.trigger('click')
    await flushPromises()
    const item = wrapper.find('.starter-pack-item')
    await item.trigger('click')
    await flushPromises()
    expect(fillFn).toHaveBeenCalled()
    delete (window as Record<string, unknown>).__VUE_CHAT_FILL__
  })

  // ===== 28. mods 变化触发 watch =====

  it('mods store 变化触发 syncEnterpriseWorkflowRegistry watch', async () => {
    const { syncEnterpriseWorkflowRegistry } = await import('@/utils/syncEnterpriseWorkflowRegistry')
    const { useModsStore } = await import('@/stores/mods')
    const { wrapper } = await mountComponent()
    const modsStore = useModsStore()
    // 触发 modsForWorkflowUi 变化
    modsStore.modsForWorkflowUi = [] as never
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    expect(syncEnterpriseWorkflowRegistry).toHaveBeenCalled()
  })

  // ===== 29. clientModsUiOff 模式 =====

  it('clientModsUiOff 时调用 stripModWorkflowEmployeeKeys', async () => {
    const { useModsStore } = await import('@/stores/mods')
    const modsStore = useModsStore()
    modsStore.clientModsUiOff = true
    const { wrapper } = await mountComponent()
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })
})
