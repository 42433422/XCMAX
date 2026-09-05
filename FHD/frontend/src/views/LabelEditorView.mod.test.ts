import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, defineComponent, ref } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import LabelEditorView from '../../../mods/xcagi-erp-domain-bridge/frontend/views/LabelEditorView.vue'
import { useTpTemplateActions } from '../../../mods/xcagi-erp-domain-bridge/frontend/views/template-preview/useTpTemplateActions'
import { normalizeLabelFields } from '../../../mods/xcagi-erp-domain-bridge/frontend/views/label-editor/leTemplateData'
import type { TplRecord } from '../../../mods/xcagi-erp-domain-bridge/frontend/views/template-preview/tpTemplateMeta'

vi.mock('@/utils/appDialog', () => ({ appAlert: vi.fn().mockResolvedValue(undefined), appConfirm: vi.fn() }))

const source = {
  id: 'db:42', name: '客户甲 80×50 标签', category: 'label', template_type: '标签',
  fields: [{
    id: 'sku-code', label: '订单货号', value: 'SKU-42', type: 'dynamic',
    binding: { column: 'sku' }, font_size: 18,
    position: { left: 26, top: 48, width: 186, height: 32, unit: 'px' },
  }],
  preview_data: {
    grid: { horizontal_lines: [0, 48, 120], vertical_lines: [0, 200, 640] },
    image_size: { width: 640, height: 400, dpi: 203 },
    layout: { paper_width_mm: 80, paper_height_mm: 50 },
    style: { font_family: 'Arial' },
  },
}

let wrapper: VueWrapper | undefined
let fetchMock: ReturnType<typeof vi.fn>
let detail: Record<string, unknown>
let failLoad: boolean
let failSave: boolean
let savedPayload: Record<string, unknown> | undefined

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

beforeEach(() => {
  detail = JSON.parse(JSON.stringify(source))
  failLoad = false
  failSave = false
  savedPayload = undefined
  document.cookie = 'csrf_token=editor-test-csrf; path=/'
  const draw = new Proxy({}, { get: (_target, key) => key === 'measureText' ? () => ({ width: 50 }) : vi.fn() })
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(draw as CanvasRenderingContext2D)
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (String(url).endsWith('/api/templates/db:42')) {
      return failLoad ? response({ message: '所选模板暂时无法读取' }, 503) : response({ success: true, template: detail })
    }
    if (String(url).endsWith('/api/templates/create')) {
      if (failSave) return response({ message: '会话已过期，请重新登录' }, 401)
      savedPayload = JSON.parse(String(init?.body)) as Record<string, unknown>
      return response({ success: true, template: { ...savedPayload, id: 'db:99' } })
    }
    if (String(url).endsWith('/api/templates/analyze')) return response({ success: false, message: '识别服务不可用' }, 503)
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.cookie = 'csrf_token=; Max-Age=0; path=/'
})

async function openEditor(path = '/label-editor?templateId=db:42') {
  const list = defineComponent({
    setup() {
      const actions = useTpTemplateActions({ refreshTemplates: vi.fn(), templates: ref([]), exportScopedTemplates: computed(() => []) })
      return { open: () => actions.openTemplateTarget({ id: 'db:42', category: 'label', name: '过期列表名称', fields: [] } as TplRecord) }
    },
    template: '<button @click="open">打开所选标签模板</button>',
  })
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/list', component: list },
    { path: '/label-editor', component: LabelEditorView },
    { path: '/template-preview', component: { template: '<div>模板列表</div>' } },
  ] })
  await router.push(path)
  await router.isReady()
  wrapper = mount({ template: '<router-view />' }, { global: { plugins: [router] } })
  await flushPromises()
  return router
}

function saveButton() {
  return wrapper!.findAll('button').find(button => /另存为新模板|保存新模板/.test(button.text()))!
}

describe('selected label template editing', () => {
  it('opens only the selected ID and renders its fetched name, fields and canvas layout', async () => {
    const router = await openEditor('/list')
    await wrapper!.get('button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ templateId: 'db:42' })
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/templates\/db:42$/), expect.objectContaining({ credentials: 'include' }))
    expect(wrapper!.get('input[aria-label="模板名称"]').element).toHaveProperty('value', source.name)
    expect(wrapper!.get('.fields-list').text()).toContain('订单货号')
    expect(wrapper!.get('.fields-list').text()).toContain('SKU-42')
    expect(wrapper!.text()).not.toContain('示例产品')
    expect(wrapper!.get('canvas').attributes()).toMatchObject({ width: '640', height: '400' })
    await wrapper!.get('.field-item').trigger('click')
    expect(wrapper!.get('input[placeholder="X"]').element).toHaveProperty('value', '26')
    expect(wrapper!.get('input[placeholder="Y"]').element).toHaveProperty('value', '48')
  })

  it('saves a new authenticated copy with edited fields, geometry and all existing layout metadata', async () => {
    await openEditor()
    await wrapper!.get('.field-item').trigger('click')
    await wrapper!.get('input[placeholder="X"]').setValue(81)
    await saveButton().trigger('click')
    await flushPromises()
    const createCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/create'))!
    expect(createCall[1]).toMatchObject({ method: 'POST', credentials: 'include', headers: {
      'X-CSRF-Token': 'editor-test-csrf', 'X-XCMAX-Client-Shell': 'enterprise',
    } })
    expect(savedPayload).toMatchObject({ name: `${source.name}（副本）`, category: 'label', preview_data: source.preview_data })
    expect(savedPayload).not.toHaveProperty('id')
    expect((savedPayload!.fields as Record<string, unknown>[])[0]).toMatchObject({
      id: 'sku-code', binding: { column: 'sku' }, font_size: 18,
      position: { left: 81, top: 48, width: 186, height: 32, unit: 'px' },
    })
    expect(detail).toEqual(source)
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/update'))).toBe(false)
    expect(wrapper!.text()).toContain('模板列表')
  })

  it('shows load failure without sample fields and disables saving until retry succeeds', async () => {
    failLoad = true
    await openEditor()
    expect(wrapper!.get('[role="alert"]').text()).toContain('所选模板暂时无法读取')
    expect(wrapper!.findAll('.field-item')).toHaveLength(0)
    expect(saveButton().attributes()).toHaveProperty('disabled')
    await saveButton().trigger('click')
    expect(savedPayload).toBeUndefined()
    failLoad = false
    await wrapper!.findAll('button').find(button => button.text() === '重新加载')!.trigger('click')
    await flushPromises()
    expect(wrapper!.findAll('.field-item')).toHaveLength(1)
    expect(saveButton().attributes()).not.toHaveProperty('disabled')
  })

  it.each([
    ['fields missing positions', { ...source, fields: [{ id: 'a', label: '真实字段' }] }],
    ['wrong returned template', { ...source, id: 'db:88' }],
    ['invalid grid layout', { ...source, preview_data: { grid: 'invalid' } }],
    ['invalid field dimensions', { ...source, fields: [{ ...source.fields[0], position: { ...source.fields[0].position, width: 'bad' } }] }],
  ])('blocks saving %s without substituting sample data', async (_label, invalid) => {
    detail = invalid
    await openEditor()
    expect(wrapper!.find('[role="alert"]').exists()).toBe(true)
    expect(wrapper!.findAll('.field-item')).toHaveLength(0)
    expect(saveButton().attributes()).toHaveProperty('disabled')
  })

  it('keeps edits after an authenticated save fails, and retries the same new-copy request', async () => {
    await openEditor()
    await wrapper!.get('input[aria-label="模板名称"]').setValue('客户甲新版')
    failSave = true
    await saveButton().trigger('click')
    await flushPromises()
    expect(wrapper!.get('[role="alert"]').text()).toContain('编辑内容已保留')
    expect(wrapper!.get('input[aria-label="模板名称"]').element).toHaveProperty('value', '客户甲新版')
    failSave = false
    await saveButton().trigger('click')
    await flushPromises()
    expect(savedPayload!.name).toBe('客户甲新版')
    expect(detail).toEqual(source)
  })

  it('starts new templates empty, without inventing a product or date', async () => {
    await openEditor('/label-editor?mode=create&name=新建客户标签')
    expect(wrapper!.findAll('.field-item')).toHaveLength(0)
    expect(wrapper!.text()).not.toContain('示例产品')
    expect(saveButton().attributes()).toHaveProperty('disabled')
    expect(wrapper!.get('input[aria-label="模板名称"]').element).toHaveProperty('value', '新建客户标签')
  })

  it('retains the loaded template when authenticated image analysis fails', async () => {
    await openEditor()
    const input = wrapper!.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      configurable: true, value: [new File(['image'], 'replacement.png', { type: 'image/png' })],
    })
    await input.trigger('change')
    await vi.waitFor(() => expect(wrapper!.text()).toContain('识别服务不可用'))
    expect(wrapper!.get('.fields-list').text()).toContain('SKU-42')
    expect(wrapper!.get('.fields-list').text()).not.toContain('示例产品')
    const uploadCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/analyze'))!
    expect(uploadCall[1]).toMatchObject({ method: 'POST', credentials: 'include', headers: { 'X-CSRF-Token': 'editor-test-csrf' } })
    await saveButton().trigger('click')
    await flushPromises()
    expect((savedPayload!.fields as unknown[])[0]).toEqual(source.fields[0])
    expect(detail).toEqual(source)
  })

  it('uses canvas coordinates when a field is dragged after zooming', async () => {
    await openEditor()
    const canvas = wrapper!.get('canvas')
    vi.spyOn(canvas.element, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 1280, height: 800 } as DOMRect)
    await canvas.trigger('mousedown', { clientX: 60, clientY: 104 })
    await canvas.trigger('mousemove', { clientX: 160, clientY: 144 })
    await canvas.trigger('mouseup')
    expect(wrapper!.get('input[placeholder="X"]').element).toHaveProperty('value', '76')
    expect(wrapper!.get('input[placeholder="Y"]').element).toHaveProperty('value', '68')
  })

  it('preserves zero values and string IDs while rejecting geometry loss', () => {
    expect(normalizeLabelFields([{ ...source.fields[0], value: 0 }])[0]).toMatchObject({ id: 'sku-code', value: '0' })
    expect(() => normalizeLabelFields([{ label: '真实字段' }])).toThrow('位置')
  })
})
