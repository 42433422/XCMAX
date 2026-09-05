import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { computed, defineComponent, h, ref } from 'vue'
import { useEtlFolderBatch } from '@/composables/useEtlFolderBatch'
import { createMemoryHistory, createRouter } from 'vue-router'
import ModProductsView from '../../../mods/xcagi-erp-domain-bridge/frontend/views/ProductsView.vue'
import HostProductsView from './ProductsView.vue'
import { createEtlCenterState } from './etlCenter/etlCenterState'
import { createEtlCenterRuns } from './etlCenter/useEtlCenterRuns'
import { useProductsStore } from '@/stores/products'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import type { EtlRun } from '@/api/etl'

const api = vi.hoisted(() => ({ getProducts: vi.fn(), getCustomers: vi.fn(), updateProduct: vi.fn(), execute: vi.fn(), upload: vi.fn(), preview: vi.fn(), run: vi.fn(), runs: vi.fn(), rollback: vi.fn() }))
vi.mock('@/api/products', () => ({ default: api }))
vi.mock('@/api/etl', () => ({ etlApi: api }))
vi.mock('@/api/customers', () => ({ default: api }))
vi.mock('@/api/templatePreview', () => ({ default: { listTemplates: vi.fn().mockResolvedValue({ success: true, templates: [] }) } }))
vi.mock('@/utils/appDialog', () => ({ appAlert: vi.fn() }))
vi.mock('@/composables/useCoreNavLabel', () => ({ useCoreNavLabel: () => '产品' }))
let price = 99
let run: EtlRun
let wrapper: VueWrapper | undefined
const Table = defineComponent({ props: ['data'], template: '<div><div v-for="row in data" :key="row.id" class="product-row"><span class="product-price">{{ row.price }}</span><slot name="actions" :row="row" /></div></div>' })
const Shell = defineComponent({ template: '<RouterView v-slot="{ Component }"><KeepAlive><component :is="Component" /></KeepAlive></RouterView>' })
function fixture(status = 'preview_ready'): EtlRun {
  return { id: 'run-price-update', upload_id: 'upload-1', file_name: 'prices.xlsx', file_sha256: 'abc', target_type: 'products', status,
    stage: status, progress: 100, total_rows: 1, processed_rows: 1, summary: { new: 0, update: 1, skip: 0, error: 0, executed: status === 'preview_ready' ? 0 : 1 },
    details: {}, source_features: {}, draft: {}, receipt: {}, reversible: true }
}
async function setup(view = ModProductsView) {
  const pinia = createPinia(); setActivePinia(pinia)
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/products', component: view }, { path: '/business-docking', component: { template: '<div>数据对接</div>' } },
  ] })
  await router.push('/products'); await router.isReady()
  wrapper = mount(Shell, { global: { plugins: [pinia, router], stubs: { DataTable: Table, ConfirmDialog: true } } })
  await flushPromises()
  const state = createEtlCenterState(); state.currentRun.value = run
  const etl = createEtlCenterRuns({ state, router, route: { query: {} }, canExecute: computed(() => true), canRollback: computed(() => true), shipmentTemplateCandidates: computed(() => []), bulkNewRows: computed(() => []) })
  return { router, etl, state, store: useProductsStore() }
}
const rowPrice = () => wrapper!.get('.product-price').text()
const editButton = () => wrapper!.findAll('button').find(button => button.text() === '编辑')!
beforeEach(() => {
  vi.clearAllMocks(); updateProductReadAccountScope({ tenantId: 1, marketUserId: 11 }); price = 99; run = fixture()
  api.getCustomers.mockResolvedValue({ success: true, data: [{ unit_name: '客户甲' }] })
  api.getProducts.mockImplementation(async () => ({ success: true, data: [{ id: 1, name: 'PM90', model_number: 'PM90-001', specification: '人工规格', price }], total: 1 }))
  api.run.mockImplementation(async () => run); api.runs.mockImplementation(async () => [run])
  api.execute.mockImplementation(async () => { price = 109; run = fixture('completed'); return run })
  api.rollback.mockImplementation(async () => { price = 99; run = { ...run, rollback_status: 'completed', receipt: { rollback: { status: 'completed', rows: 1 } } }; return run })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks(); vi.useRealTimers() })

describe('kept-alive product freshness', () => {
  it.each([['shipped Mod', ModProductsView], ['host', HostProductsView]] as const)('%s shows 99 → import 109 → rollback 99 without a document reload', async (_label, view) => {
    const { router, etl } = await setup(view)
    expect(rowPrice()).toBe('99')
    await router.push('/business-docking'); await flushPromises()
    await etl.executeCurrentRun()
    await router.push('/products'); await flushPromises()
    expect(rowPrice()).toBe('109'); expect(editButton().attributes('disabled')).toBeUndefined()
    await router.push('/business-docking'); await flushPromises()
    await etl.rollbackRun()
    await router.push('/products'); await flushPromises()
    expect(rowPrice()).toBe('99'); expect(api.execute).toHaveBeenCalledTimes(1); expect(api.rollback).toHaveBeenCalledTimes(1)
  })

  it('observes asynchronous completion through the actual ETL poll before revisiting products', async () => {
    const { router, etl, state } = await setup()
    await router.push('/business-docking'); await flushPromises()
    vi.useFakeTimers()
    api.execute.mockImplementationOnce(async () => { run = { ...fixture(), status: 'executing' }; return run })
    await etl.executeCurrentRun()
    expect(state.currentRun.value?.status).toBe('executing')
    price = 109; run = fixture('completed')
    await vi.advanceTimersByTimeAsync(1200)
    expect(state.currentRun.value?.status).toBe('completed')
    vi.useRealTimers()
    await router.push('/products'); await flushPromises()
    expect(rowPrice()).toBe('109')
  })

  it('folder polling updates a product page that stays visible, without relying on activation', async () => {
    const { router, etl, state } = await setup()
    let batch!: ReturnType<typeof useEtlFolderBatch>
    const BatchHarness = defineComponent({ setup() {
      batch = useEtlFolderBatch({ capabilities: state.capabilities, targetType: state.targetType,
        templateId: ref(''), compatibilityPresetId: ref(''), targetConfigId: ref(''), runs: state.runs,
        currentRun: state.currentRun, activeTab: state.activeTab, busy: state.busy, pageError: state.pageError,
        router, autoWriteEnabled: ref(true), markAutoWrite: etl.markAutoWrite, tryAutoWrite: etl.tryAutoWrite,
        syncDraft: etl.syncDraft, schedulePoll: etl.schedulePoll, loadRows: etl.loadRows })
      return () => h('div')
    } })
    const harness = mount(BatchHarness, { global: { stubs: { DataTable: Table, ConfirmDialog: true } } })
    const replace = vi.spyOn(router, 'replace').mockResolvedValue(undefined)
    try {
      api.upload.mockResolvedValue({ upload_id: 'batch-upload' })
      api.preview.mockImplementation(async () => ({ ...fixture(), status: 'executing' }))
      batch.onFileChange({ target: { files: [new File(['a'], 'first.xlsx'), new File(['b'], 'second.xlsx')] } } as unknown as Event)
      vi.useFakeTimers()
      await batch.startPreview()
      expect(rowPrice()).toBe('99')
      price = 109; run = fixture('completed')
      await vi.advanceTimersByTimeAsync(1500)
      await flushPromises()
      expect(rowPrice()).toBe('109')
      expect(router.currentRoute.value.path).toBe('/products')
    } finally { harness.unmount(); replace.mockRestore(); vi.useRealTimers() }
  })

  it('auto-write refreshes a visible product list through the same notification path', async () => {
    const { etl, state } = await setup()
    state.autoWriteEnabled.value = true
    etl.markAutoWrite(run.id)
    await etl.tryAutoWrite(run); await flushPromises()
    expect(rowPrice()).toBe('109'); expect(api.execute).toHaveBeenCalledTimes(1)
  })

  it('re-reads changes from a partially failed rollback while preserving its failure', async () => {
    const { router, etl, state } = await setup()
    await router.push('/business-docking'); await flushPromises()
    await etl.executeCurrentRun()
    api.rollback.mockImplementationOnce(async () => { price = 99; throw new Error('部分撤销后失败') })
    await etl.rollbackRun()
    expect(state.pageError.value).toContain('部分撤销后失败')
    await router.push('/products'); await flushPromises()
    expect(rowPrice()).toBe('99')
  })

  it('re-reads partial writes on failure without turning the failed ETL action into success', async () => {
    const { router, etl, state } = await setup()
    await router.push('/business-docking'); await flushPromises()
    api.execute.mockImplementationOnce(async () => { price = 109; run = fixture('failed'); throw new Error('第二行失败，第一行已写入') })
    await etl.executeCurrentRun()
    expect(state.pageError.value).toContain('第二行失败'); expect(state.currentRun.value?.status).toBe('failed')
    await router.push('/products'); await flushPromises()
    expect(rowPrice()).toBe('109')
  })

  it('refresh failure keeps the known price visible but blocks editing until a successful retry', async () => {
    const { store } = await setup()
    api.getProducts.mockRejectedValueOnce(new Error('无法读取'))
    store.invalidateProducts(); await flushPromises()
    expect(rowPrice()).toBe('99'); expect(wrapper!.get('[role="status"]').text()).toContain('产品读取失败')
    expect(editButton().attributes('disabled')).toBeDefined()
    await editButton().trigger('click'); expect(wrapper!.find('.modal').exists()).toBe(false)
    price = 109
    await wrapper!.findAll('button').find(button => button.text() === '重新读取')!.trigger('click'); await flushPromises()
    expect(rowPrice()).toBe('109'); expect(editButton().attributes('disabled')).toBeUndefined()
  })

  it('account switching clears an open edit form and prevents old rows remaining on a kept-alive page', async () => {
    const { store } = await setup()
    await editButton().trigger('click'); expect(wrapper!.find('.modal').exists()).toBe(true)
    price = 88
    updateProductReadAccountScope({ tenantId: 2, marketUserId: 22 })
    expect(store.products).toEqual([])
    await flushPromises()
    expect(wrapper!.find('.modal').exists()).toBe(false); expect(rowPrice()).toBe('88')
  })

  it('returning to a retained page retires its old edit form before reading the latest price', async () => {
    const { router } = await setup()
    await editButton().trigger('click')
    await router.push('/business-docking'); await flushPromises()
    price = 109
    await router.push('/products'); await flushPromises()
    expect(wrapper!.find('.modal').exists()).toBe(false); expect(rowPrice()).toBe('109')
  })

  it('external data invalidation closes an old-price edit form instead of silently making it writable after refresh', async () => {
    const { store } = await setup()
    await editButton().trigger('click'); expect(wrapper!.find('.modal').exists()).toBe(true)
    price = 109; store.invalidateProducts(); await flushPromises()
    expect(wrapper!.find('.modal').exists()).toBe(false)
    expect(wrapper!.get('[role="status"]').text()).toContain('请重新选择产品后编辑')
    await editButton().trigger('click')
    expect(wrapper!.get('.modal input[type="number"]').element.value).toBe('109')
  })
})
