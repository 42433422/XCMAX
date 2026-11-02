import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import TemplatePreviewView from '../../../mods/xcagi-erp-domain-bridge/frontend/views/TemplatePreviewView.vue'
import { useTpGridTool } from '../../../mods/xcagi-erp-domain-bridge/frontend/views/template-preview/useTpGridTool'

const mocks = vi.hoisted(() => ({ assemble: vi.fn(), extractGrid: vi.fn(), alert: vi.fn() }))
vi.mock('../../../mods/xcagi-erp-domain-bridge/frontend/views/template-preview/assemble', () => ({ assembleTemplatePreview: mocks.assemble }))
vi.mock('@/api/templatePreview', () => ({ default: { extractGrid: mocks.extractGrid } }))
vi.mock('@/utils/appDialog', () => ({ appAlert: mocks.alert }))

let wrapper: VueWrapper | undefined
let tool: ReturnType<typeof useTpGridTool>
const input = () => wrapper!.get<HTMLInputElement>('input[type="file"]')
const picker = () => wrapper!.get<HTMLButtonElement>('.grid-tool-actions .btn-secondary')
const extract = () => wrapper!.get<HTMLButtonElement>('.grid-tool-actions .btn-primary')
async function select(files: File[]) {
  Object.defineProperty(input().element, 'files', { configurable: true, value: files })
  await input().trigger('change')
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.alert.mockResolvedValue(undefined)
  tool = useTpGridTool()
  mocks.assemble.mockReturnValue({ ...tool, scopeTabs: ref([]), activeScopeTab: ref('all'), refreshTemplates: vi.fn(), openCreateModal: vi.fn(), loading: ref(false), error: ref(''), filteredTemplates: ref([]) })
  wrapper = shallowMount(TemplatePreviewView, { attachTo: document.body })
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks() })

describe('template library grid file picker', () => {
  it('uses the platform button to open the native Excel chooser and shows its empty state', async () => {
    expect(picker().classes()).toEqual(expect.arrayContaining(['btn', 'btn-sm', 'btn-secondary']))
    expect(picker().attributes('type')).toBe('button')
    expect(picker().text()).toContain('选择')
    expect(input().attributes('accept')).toBe('.xlsx,.xls')
    expect(input().attributes('aria-label')).toBe('选择 Excel 文件')
    expect(input().attributes('tabindex')).toBe('-1')
    expect(wrapper!.get('[role="status"]').text()).toBe('未选择文件')
    expect(extract().element.disabled).toBe(true)
    const click = vi.spyOn(input().element, 'click').mockImplementation(() => undefined)
    picker().element.focus()
    expect(document.activeElement).toBe(picker().element)
    await picker().trigger('click')
    expect(click).toHaveBeenCalledOnce()
    expect(mocks.extractGrid).not.toHaveBeenCalled()
  })

  it('retains the selected file and visible name when the chooser is cancelled', async () => {
    await select([])
    expect(tool.gridToolFile.value).toBeNull()
    const file = new File(['synthetic'], '报价模板.xlsx')
    await select([file])
    expect(wrapper!.get('[role="status"]').text()).toBe(file.name)
    expect(wrapper!.get('[role="status"]').attributes('title')).toBe(file.name)
    await input().trigger('cancel')
    await select([])
    expect(tool.gridToolFile.value).toBe(file)
    expect(wrapper!.get('[role="status"]').text()).toBe(file.name)
    expect(extract().element.disabled).toBe(false)
  })

  it('resets the native value after each selection so the same file can be selected again', async () => {
    const file = new File(['synthetic'], 'same.xlsx')
    const reset = vi.spyOn(input().element, 'value', 'set')
    await select([file])
    await select([file])
    expect(reset.mock.calls).toEqual([[''], ['']])
    expect(tool.gridToolFile.value).toBe(file)
    expect(wrapper!.get('[role="status"]').text()).toBe(file.name)
  })

  it('disables both controls, ignores new selections and submits once during repeated extraction', async () => {
    let finish!: (value: { success: boolean; fields: unknown[] }) => void
    mocks.extractGrid.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const file = new File(['synthetic'], 'first.xlsx')
    await select([file])
    const pending = tool.extractGridFromExcel()
    const duplicate = tool.extractGridFromExcel()
    await nextTick()
    expect(mocks.extractGrid).toHaveBeenCalledOnce()
    expect((mocks.extractGrid.mock.calls[0][0] as FormData).get('file')).toBe(file)
    expect(picker().element.disabled).toBe(true)
    expect(input().element.disabled).toBe(true)
    expect(extract().element.disabled).toBe(true)
    const click = vi.spyOn(input().element, 'click').mockImplementation(() => undefined)
    picker().element.click()
    expect(click).not.toHaveBeenCalled()
    await select([new File(['other'], 'second.xlsx')])
    expect(tool.gridToolFile.value).toBe(file)
    finish({ success: true, fields: [] })
    await Promise.all([pending, duplicate])
    await flushPromises()
    expect(tool.extractingGrid.value).toBe(false)
    expect(tool.showGridToolModal.value).toBe(true)
    expect(picker().element.disabled).toBe(false)
    expect(input().element.disabled).toBe(false)
    expect(extract().element.disabled).toBe(false)
  })

  it('allows retry after extraction fails without losing the selected file', async () => {
    mocks.extractGrid.mockRejectedValueOnce(new Error('合成失败')).mockResolvedValueOnce({ success: true, fields: [] })
    const file = new File(['synthetic'], 'retry.xls')
    await select([file])
    await tool.extractGridFromExcel()
    await nextTick()
    expect(mocks.alert).toHaveBeenCalledWith('网格提取失败：合成失败')
    expect(tool.gridToolFile.value).toBe(file)
    expect(extract().element.disabled).toBe(false)
    await tool.extractGridFromExcel()
    expect(mocks.extractGrid).toHaveBeenCalledTimes(2)
    expect(tool.showGridToolModal.value).toBe(true)
  })
})
