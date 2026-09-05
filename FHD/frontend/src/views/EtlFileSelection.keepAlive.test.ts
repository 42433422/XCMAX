import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { defineComponent } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EtlCenterView from './EtlCenterView.vue'

const api = vi.hoisted(() => ({
  capabilities: vi.fn(),
  templates: vi.fn(),
  runs: vi.fn(),
  targetConfigs: vi.fn(),
  upload: vi.fn(),
  preview: vi.fn(),
  rows: vi.fn(),
  run: vi.fn(),
  execute: vi.fn(),
  exportUrl: vi.fn(),
  errorExportUrl: vi.fn(),
}))
vi.mock('@/api/etl', () => ({ etlApi: api }))
vi.mock('@/api/auth', () => ({
  authApi: { getCurrentUser: vi.fn().mockResolvedValue({ success: true, data: { permissions: ['etl.read', 'etl.execute'] } }) },
}))
const Shell = defineComponent({
  template:
    '<RouterView v-slot="{ Component, route }"><KeepAlive :max="12"><component :is="Component" :key="String(route.name || route.path)" /></KeepAlive></RouterView>',
})
let wrapper: VueWrapper | undefined
const completed = {
  id: 'first-run',
  upload_id: 'first-upload',
  file_name: 'products-create.csv',
  file_sha256: 'test',
  target_type: 'customer_products',
  status: 'completed',
  stage: 'completed',
  progress: 100,
  total_rows: 1,
  processed_rows: 1,
  summary: { new: 1, update: 0, skip: 0, error: 0, executed: 1 },
  details: {},
  source_features: {},
  draft: {},
  receipt: {},
  reversible: true,
}
const button = (text: string) => wrapper!.findAll('button').find((item) => item.text() === text)!
async function setup() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/business-docking', name: 'business-docking', component: EtlCenterView },
      { path: '/products', name: 'products', component: { template: '<div>产品列表</div>' } },
      { path: '/customers', component: { template: '<div>客户列表</div>' } },
    ],
  })
  await router.push('/business-docking')
  await router.isReady()
  wrapper = mount(Shell, { attachTo: document.body, global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return router
}
function input(folder = false) {
  return wrapper!.get<HTMLInputElement>(folder ? 'input[webkitdirectory]' : 'input[type="file"]:not([webkitdirectory])')
}
async function choose(file: File, folder = false) {
  Object.defineProperty(input(folder).element, 'files', { value: [file], configurable: true })
  await input(folder).trigger('change')
}
beforeEach(() => {
  vi.clearAllMocks()
  api.capabilities.mockResolvedValue({
    enabled: true,
    limits: { max_file_bytes: 100 * 1024 * 1024 },
    targets: [
      { type: 'customer_products', label: '客户及产品', fields: [], supported_actions: ['new', 'update', 'skip'], reversible: true },
    ],
    compatibility_presets: [],
    inputs: {},
    transforms: [],
  })
  api.templates.mockResolvedValue([])
  api.runs.mockResolvedValue([])
  api.targetConfigs.mockResolvedValue([])
  api.upload.mockResolvedValue({ upload_id: completed.upload_id })
  api.preview.mockResolvedValue(completed)
  api.run.mockResolvedValue(completed)
  api.rows.mockResolvedValue({ items: [], total: 0 })
  api.exportUrl.mockReturnValue('/export')
  api.errorExportUrl.mockReturnValue('/errors')
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
})
describe('ETL input through the actual kept-alive route and upload panel', () => {
  it.each([
    ['next file', false, 'products-update-price.csv'],
    ['same file', false, 'products-create.csv'],
    ['whole folder', true, 'products-update-price.csv'],
  ] as const)('selects %s once after a completed import, product navigation, and clear', async (_case, folder, name) => {
    const router = await setup()
    const first = input().element
    await choose(new File(['model,price\nPM90-001,99'], 'products-create.csv'))
    await button('上传并写入数据库').trigger('click')
    await flushPromises()
    await button('1 上传文件').trigger('click')
    await flushPromises()
    const remounted = input().element
    expect(remounted).not.toBe(first)
    expect(wrapper!.get('.etl-batch-card').text()).toContain('100%')
    await router.push('/products')
    await flushPromises()
    await router.push('/business-docking')
    await flushPromises()
    await button('清空').trigger('click')
    await flushPromises()
    expect(wrapper!.find('.etl-batch-card').exists()).toBe(false)
    const click = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(function (this: HTMLInputElement) {
      expect(this).toBe(input(folder).element)
      expect(this.isConnected).toBe(true)
    })
    await button(folder ? '选择整个文件夹' : '选择文件').trigger('click')
    expect(click).toHaveBeenCalledTimes(1)
    const nextFile = new File(['model,price\nPM90-001,109'], name)
    if (folder) Object.defineProperty(nextFile, 'webkitRelativePath', { value: `客户产品/${name}` })
    await choose(nextFile, folder)
    expect(wrapper!.get('.etl-batch-card').text()).toContain(folder ? `客户产品/${name}` : name)
    expect(button('上传并写入数据库').attributes('disabled')).toBeUndefined()
    expect(api.upload).toHaveBeenCalledTimes(1)
  })
})
