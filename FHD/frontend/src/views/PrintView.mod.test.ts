import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import PrintView from '../../../mods/xcagi-erp-domain-bridge/frontend/views/PrintView.vue'

let wrapper: VueWrapper | undefined
let fetchMock: ReturnType<typeof vi.fn>
let failDetail: boolean
let failGenerate: boolean
let submitMode: 'submitted' | 'failed' | 'outcome_unknown' | 'network'
const template = {
  id: 'db:42', name: '指定标签模板', category: 'label', fields: [],
  preview_data: { image_size: { width: 640, height: 400 }, layout: { paper_width_mm: 80, paper_height_mm: 50 } },
}
const baseJob = { id: 'a'.repeat(32), status: 'generated', message: '标签 PDF 已生成', product_id: 2, product_name: '同名产品', template_id: 'db:42', template_name: '指定标签模板', copies: 3, paper_width_mm: 80, paper_height_mm: 50 }
function response(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }) }
function button(text: string) { return wrapper!.findAll('button').find(b => b.text() === text)! }
async function chooseAndGenerate() {
  await wrapper!.get('#label-product').setValue('2')
  await wrapper!.get('#label-template').setValue('db:42')
  await flushPromises()
  await wrapper!.get('#label-copies').setValue(3)
  await button('生成标签 PDF').trigger('click')
  await flushPromises()
}
beforeEach(async () => {
  failDetail = false; failGenerate = false; submitMode = 'submitted'
  document.cookie = 'csrf_token=label-csrf; path=/'
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:label-file'), revokeObjectURL: vi.fn() }))
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/label-jobs/products') && url.includes('page=2')) return response({ success: true, total: 3, data: [{ id: 2000, name: '末页产品', model_number: 'LAST' }] })
    if (url.includes('/label-jobs/products') && url.includes('keyword=LAST')) return response({ success: true, total: 1, data: [{ id: 2000, name: '末页产品', model_number: 'LAST' }] })
    if (url.includes('/label-jobs/products')) return response({ success: true, total: 3, data: [{ id: 1, name: '同名产品', model_number: 'SKU-1' }, { id: 2, name: '同名产品', model_number: 'SKU-2' }] })
    if (url.endsWith('/api/templates')) return response({ success: true, templates: [template, { id: 'db:55', category: 'excel', name: '发货单' }] })
    if (url.endsWith('/api/templates/db:42')) return failDetail ? response({ message: '模板载入失败' }, 503) : response({ success: true, template })
    if (url.endsWith('/api/print/label-jobs')) return failGenerate ? response({ message: '字段缺少产品绑定' }, 400) : response({ success: true, job: baseJob })
    if (url.endsWith('/file')) return new Response(new Blob(['%PDF-1.7 real generated test artifact'], { type: 'application/pdf' }), { headers: { 'Content-Type': 'application/pdf' } })
    if (url.endsWith('/confirmation')) return response({ success: true, job: baseJob, confirm_token: 'confirmed-on-server-123456', confirm_prompt: '确认将 3 张 80 × 50 mm 标签提交到 LabelPrinter？' })
    if (url.endsWith('/submit')) {
      if (submitMode === 'network') throw new Error('连接中断')
      return response({ success: true, job: { ...baseJob, status: submitMode, message: submitMode === 'submitted' ? '已提交打印队列；物理出纸仍需现场核对' : submitMode === 'failed' ? '打印服务拒绝任务' : '提交结果待确认，请检查打印队列' } })
    }
    throw new Error(`Unexpected ${init?.method} ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  wrapper = mount(PrintView)
  await flushPromises()
})
afterEach(() => {
  wrapper?.unmount(); wrapper = undefined
  vi.restoreAllMocks(); vi.unstubAllGlobals()
  document.cookie = 'csrf_token=; Max-Age=0; path=/'
})

describe('actual Mod label output flow', () => {
  it('searches and paginates the same product source as generation without silently truncating', async () => {
    expect(wrapper!.text()).toContain('已显示 2 / 3')
    await button('加载更多产品').trigger('click'); await flushPromises()
    expect(wrapper!.get('#label-product').text()).toContain('末页产品')
    expect(wrapper!.text()).toContain('已显示 3 / 3')
    await wrapper!.get('#label-search').setValue('LAST')
    await button('搜索产品').trigger('click'); await flushPromises()
    expect(wrapper!.text()).toContain('已显示 1 / 1')
    expect(wrapper!.get('#label-product').text()).not.toContain('SKU-1')
    expect(fetchMock.mock.calls.some(call => call[0].includes('/api/mod/'))).toBe(false)
  })

  it('uses product ID, selected template and saved physical size; downloads authenticated PDF before confirmation', async () => {
    expect(wrapper!.get('#label-product').text()).toContain('编号 1')
    expect(wrapper!.get('#label-product').text()).toContain('编号 2')
    expect(wrapper!.get('#label-template').text()).not.toContain('发货单')
    await chooseAndGenerate()
    const generate = fetchMock.mock.calls.find(call => call[0].endsWith('/label-jobs'))!
    expect(JSON.parse(generate[1].body)).toEqual({ product_id: 2, template_id: 'db:42', copies: 3, paper_width_mm: 80, paper_height_mm: 50 })
    expect(generate[1].credentials).toBe('include')
    expect(generate[1].headers['X-CSRF-Token']).toBe('label-csrf')
    expect(wrapper!.get('iframe').attributes('src')).toBe('blob:label-file')
    expect(wrapper!.get('a[download]').attributes('href')).toBe('blob:label-file')
    expect(fetchMock.mock.calls.find(call => call[0].endsWith('/file'))![1].credentials).toBe('include')
    expect(fetchMock.mock.calls.filter(call => call[0].endsWith('/submit'))).toHaveLength(0)
    await button('准备打印').trigger('click'); await flushPromises()
    expect(wrapper!.get('[role="dialog"]').text()).toContain('3 张 80 × 50 mm')
    expect(fetchMock.mock.calls.filter(call => call[0].endsWith('/submit'))).toHaveLength(0)
    await button('确认并提交打印').trigger('click'); await flushPromises()
    const submitted = fetchMock.mock.calls.find(call => call[0].endsWith('/submit'))!
    expect(JSON.parse(submitted[1].body)).toEqual({ confirm_token: 'confirmed-on-server-123456' })
    expect(wrapper!.text()).toContain('已提交打印队列；物理出纸仍需现场核对')
    expect(button('准备打印').attributes('disabled')).toBeDefined()
  })
  it('never substitutes a template when loading fails and permits retry', async () => {
    failDetail = true
    await wrapper!.get('#label-product').setValue('2')
    await wrapper!.get('#label-template').setValue('db:42'); await flushPromises()
    expect(button('生成标签 PDF').attributes('disabled')).toBeDefined()
    expect(wrapper!.text()).toContain('模板载入失败')
    failDetail = false
    await button('重试模板加载').trigger('click'); await flushPromises()
    expect(button('生成标签 PDF').attributes('disabled')).toBeUndefined()
  })
  it('retains choices after generation failure and can retry without sample output', async () => {
    failGenerate = true
    await chooseAndGenerate()
    expect(wrapper!.text()).toContain('字段缺少产品绑定')
    expect(wrapper!.find('iframe').exists()).toBe(false)
    expect((wrapper!.get('#label-product').element as HTMLSelectElement).value).toBe('2')
    failGenerate = false
    await button('生成标签 PDF').trigger('click'); await flushPromises()
    expect(wrapper!.find('iframe').exists()).toBe(true)
  })
  it('allows explicit rejected jobs to be confirmed again', async () => {
    submitMode = 'failed'
    await chooseAndGenerate()
    await button('准备打印').trigger('click'); await flushPromises()
    await button('确认并提交打印').trigger('click'); await flushPromises()
    expect(wrapper!.text()).toContain('打印服务拒绝任务')
    expect(button('重新确认打印').attributes('disabled')).toBeUndefined()
  })
  it.each(['network', 'outcome_unknown'] as const)('prevents repeat submission when %s outcome is uncertain', async mode => {
    submitMode = mode
    await chooseAndGenerate()
    await button('准备打印').trigger('click'); await flushPromises()
    await button('确认并提交打印').trigger('click'); await flushPromises()
    expect(wrapper!.text()).toContain('结果待确认')
    expect(button('准备打印').attributes('disabled')).toBeDefined()
    expect(fetchMock.mock.calls.filter(call => call[0].endsWith('/submit'))).toHaveLength(1)
  })
  it('invalidates confirmation after product selection changes', async () => {
    await chooseAndGenerate()
    await button('准备打印').trigger('click'); await flushPromises()
    await wrapper!.get('#label-product').setValue('1'); await flushPromises()
    expect(wrapper!.find('[role="dialog"]').exists()).toBe(false)
    expect(button('准备打印').attributes('disabled')).toBeDefined()
    expect(wrapper!.text()).toContain('选择已变更')
  })
})
