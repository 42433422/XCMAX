import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EtlCenterView from './EtlCenterView.vue'

const { archive, legacy } = vi.hoisted(() => ({
  archive: { archiveClassifyExcel: vi.fn(), confirmClassification: vi.fn(), reviewExcel: vi.fn(), saveReviewedExcel: vi.fn(), archiveAssets: vi.fn() },
  legacy: { capabilities: vi.fn(), templates: vi.fn(), runs: vi.fn(), targetConfigs: vi.fn(), run: vi.fn(), upload: vi.fn(), preview: vi.fn(), execute: vi.fn() },
}))
vi.mock('@/api/templatePreview', () => ({ default: archive }))
vi.mock('@/api/etl', () => ({ etlApi: legacy }))
vi.mock('@/api/auth', () => ({ authApi: { getCurrentUser: vi.fn().mockResolvedValue({ success: true, data: { permissions: ['etl.read'] } }) } }))

function region(range: string, label = 'unknown') {
  return { range, labels: [label], checked_cells: 4, parent_heading: label, dependency_status: '待确认', needs_confirmation: true,
    header_cells: [], merged_ranges: [], possible_shared_context: [], evidence: [] }
}
const parts = () => [region('A1:D4', 'process'), region('A5:D8', 'material'), region('A9:D12', 'inspection')]
const classification = (regions = parts()) => ({ name: '生产单.xlsx', classification_id: 'production', version: 'v1', status: 'classified', confirmed: false,
  model_status: 'not_called', sheets: [{ sheet: '生产单', labels: ['production'], checked_cells: 12, evidence: [], regions }] })
function review(id: string) {
  const candidates = [0, 1, 2].map(index => ({ id: `candidate-${index}`, label: `候选${index + 1}`, explanation: '保留未确认内容', clear: [] }))
  return { review_id: id, sha256: 'sha', cells: [], sheets: ['生产单'], model: 'not_called', proposal: { version: `${id}-v1`, parent_version: null,
    candidates, evidence: [], model: { status: 'not_called' }, result_previews: candidates.map(candidate => ({ candidate_id: candidate.id, sha256: 'sha', layout: [], layout_truncated: false })) } }
}
async function setup(runId = '') {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/business-docking', component: EtlCenterView }, { path: '/template-preview', component: { template: '<div>模板库</div>' } }] })
  await router.push({ path: '/business-docking', query: runId ? { run_id: runId } : {} })
  await router.isReady()
  const wrapper = mount(EtlCenterView, { global: { plugins: [router] } })
  await flushPromises()
  const button = (text: string) => wrapper.findAll('button').find(item => item.text() === text)!
  const choose = async () => {
    const input = wrapper.get('input[type="file"][multiple]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [new File(['工艺、原料、检验说明'], '生产单.xlsx')] })
    await input.trigger('change'); await flushPromises()
  }
  return { wrapper, router, button, choose }
}
beforeEach(() => {
  vi.clearAllMocks()
  archive.archiveClassifyExcel.mockResolvedValue(classification())
  archive.confirmClassification.mockImplementation(async () => ({ ...classification(), version: 'v2', confirmed: true }))
  archive.reviewExcel.mockImplementation(async (form: FormData) => review(String(form.get('region_range'))))
  archive.saveReviewedExcel.mockResolvedValue({ template_id: '21' })
  legacy.capabilities.mockResolvedValue({ targets: [], transforms: [], compatibility_presets: [], inputs: {}, limits: {} })
  legacy.templates.mockResolvedValue([]); legacy.runs.mockResolvedValue([]); legacy.targetConfigs.mockResolvedValue([])
})

afterEach(() => vi.restoreAllMocks())

describe('data docking archive-first workflow', () => {
  it('archives a production workbook on selection and never creates a default business import', async () => {
    const { wrapper, choose } = await setup()
    expect(legacy.capabilities).not.toHaveBeenCalled()
    expect(wrapper.find('.etl-dropzone').exists()).toBe(false)
    await choose()
    expect(archive.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    expect(wrapper.findAll('.classification-region')).toHaveLength(3)
    expect(wrapper.text()).toContain('工艺'); expect(wrapper.text()).toContain('原料'); expect(wrapper.text()).toContain('检验')
    expect(wrapper.find('[aria-current="step"]')?.text()).toContain('切片分类')
    expect(legacy.upload).not.toHaveBeenCalled(); expect(legacy.preview).not.toHaveBeenCalled(); expect(legacy.execute).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('requires classification confirmation and scopes each candidate/save to its selected fragment', async () => {
    const { wrapper, choose, button } = await setup(); await choose()
    expect(button('预览清理候选').attributes('disabled')).toBeDefined()
    await button('确认分类并继续').trigger('click'); await flushPromises()
    await button('预览清理候选').trigger('click'); await flushPromises()
    expect((archive.reviewExcel.mock.calls[0][0] as FormData).get('region_range')).toBe('A1:D4')
    const dispatch = vi.spyOn(window, 'dispatchEvent')
    expect((archive.reviewExcel.mock.calls[0][0] as FormData).get('classification_version')).toBe('v2')
    await wrapper.findAll('input[type="checkbox"]').find(input => input.element.closest('label')?.textContent?.includes('发布清理后的文件'))!.setValue(true)
    await button('保存所选模板').trigger('click'); await flushPromises()
    expect((archive.saveReviewedExcel.mock.calls[0][0] as FormData).get('review_id')).toBe('A1:D4')
    const events = dispatch.mock.calls.map(([event]) => event).filter(event => event.type === 'xcagi:templates-updated')
    expect(events).toHaveLength(1)
    expect((events[0] as CustomEvent).detail).toEqual({ source: 'etl-center' })
    await wrapper.findAll('input[type="radio"][name="template-region"]')[1].setValue(true)
    expect(wrapper.text()).not.toContain('已保存到模板库。')
    expect(wrapper.findAll('button').some(item => item.text() === '保存所选模板')).toBe(false)
    await button('预览清理候选').trigger('click'); await flushPromises()
    expect((archive.reviewExcel.mock.calls[1][0] as FormData).get('region_range')).toBe('A5:D8')
    expect(button('保存所选模板').attributes('disabled')).toBeDefined()
    expect(legacy.execute).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('saves an explicit split as unconfirmed and requires a second continuation review', async () => {
    archive.archiveClassifyExcel.mockResolvedValue(classification([region('A1:D8')]))
    const sheets = [{ sheet: '生产单', labels: ['unknown'], checked_cells: 8, evidence: [], regions: [region('A1:D4'), region('A5:D8')] }]
    const link = { sheet: '生产单', first: 'A1:D4', second: 'A5:D8', shared_dependencies: [], repeated_header_observed: true, status: 'candidate' }
    archive.confirmClassification.mockResolvedValueOnce({ version: 'split-v2', confirmed: false, sheets, fragment_links: { items: [link], omitted: 0 }, partition_pending: true })
      .mockResolvedValueOnce({ version: 'confirmed-v3', confirmed: true, sheets, fragment_links: { items: [link], omitted: 0 } })
    const { wrapper, choose, button } = await setup(); await choose()
    await wrapper.get('.classification-region textarea').setValue('A1:D4\nA5:D8')
    await button('拆分此片段').trigger('click')
    await button('确认分类并继续').trigger('click'); await flushPromises()
    const first = archive.confirmClassification.mock.calls[0][1] as FormData
    expect(JSON.parse(String(first.get('labels_json'))).map((part: { original_range: string }) => part.original_range)).toEqual(['A1:D8', 'A1:D8'])
    expect(wrapper.text()).toContain('拆分已保存。请核对新的文档片段和续表关系')
    expect(button('预览清理候选').attributes('disabled')).toBeDefined()
    await wrapper.findAll('input[type="checkbox"]').find(input => input.element.closest('label')?.textContent?.includes('同一文档'))!.setValue(true)
    await button('确认分类并继续').trigger('click'); await flushPromises()
    const second = archive.confirmClassification.mock.calls[1][1] as FormData
    expect(JSON.parse(String(second.get('labels_json'))).map((part: { original_range: string }) => part.original_range)).toEqual(['A1:D4', 'A5:D8'])
    expect(JSON.parse(String(second.get('links_json')))).toEqual([{ sheet: '生产单', first: 'A1:D4', second: 'A5:D8' }])
    expect(button('预览清理候选').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('previews the canonical server-confirmed coordinates after a lowercase boundary edit', async () => {
    archive.archiveClassifyExcel.mockResolvedValue(classification([region('A1:D8')]))
    archive.confirmClassification.mockResolvedValue({ ...classification([region('A1:D3')]), version: 'canonical-v2', confirmed: true })
    const { wrapper, choose, button } = await setup(); await choose()
    const boundary = wrapper.findAll('.classification-region input').find(input => input.element.closest('label')?.textContent?.includes('调整区域坐标'))!
    await boundary.setValue('a1:d3')
    await button('确认分类并继续').trigger('click'); await flushPromises()
    expect(wrapper.get<HTMLInputElement>('input[name="template-region"]').element.checked).toBe(true)
    await button('预览清理候选').trigger('click'); await flushPromises()
    const form = archive.reviewExcel.mock.calls[0][0] as FormData
    expect(form.get('classification_version')).toBe('canonical-v2')
    expect(form.get('region_sheet')).toBe('生产单')
    expect(form.get('region_range')).toBe('A1:D3')
    wrapper.unmount()
  })

  it.each([
    ['removed range', '生产单', 'A5:D8'],
    ['changed sheet', '另一张单', 'A1:D4'],
  ])('requires an explicit new selection after the server returns a %s', async (_case, sheet, range) => {
    archive.archiveClassifyExcel.mockResolvedValue(classification([region('A1:D4')]))
    const confirmed = classification([region(range)])
    confirmed.sheets[0].sheet = sheet
    archive.confirmClassification.mockResolvedValue({ ...confirmed, version: 'changed-v2', confirmed: true })
    const { wrapper, choose, button } = await setup(); await choose()
    await button('确认分类并继续').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('当前所选片段已变化，请从确认后的文档片段中重新选择')
    expect(wrapper.get<HTMLInputElement>('input[name="template-region"]').element.checked).toBe(false)
    expect(button('预览清理候选').attributes('disabled')).toBeDefined()
    await button('预览清理候选').trigger('click'); await flushPromises()
    expect(archive.reviewExcel).not.toHaveBeenCalled()
    await wrapper.get('input[name="template-region"]').setValue(true)
    expect(wrapper.text()).not.toContain('当前所选片段已变化')
    await button('预览清理候选').trigger('click'); await flushPromises()
    const form = archive.reviewExcel.mock.calls[0][0] as FormData
    expect(form.get('region_sheet')).toBe(sheet)
    expect(form.get('region_range')).toBe(range)
    wrapper.unmount()
  })

  it('keeps archive request identity when classification fails after the original may have been archived', async () => {
    archive.archiveClassifyExcel.mockRejectedValueOnce(new Error('分类结果未知'))
    const { wrapper, choose, button } = await setup(); await choose()
    expect(wrapper.text()).toContain('请先查看原件档案核对，勿重新选择文件重复上传')
    const first = archive.archiveClassifyExcel.mock.calls[0][0] as FormData
    await button('重试未完成文件').trigger('click'); await flushPromises()
    const retried = archive.archiveClassifyExcel.mock.calls[1][0] as FormData
    expect(retried.get('request_key')).toBe(first.get('request_key'))
    expect(legacy.upload).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('retries only an unfinished file while preserving its original archive identity', async () => {
    let failed = false
    archive.archiveClassifyExcel.mockImplementation(async (form: FormData) => {
      const file = form.get('file') as File
      if (file.name === 'inspection.xlsx' && !failed) { failed = true; throw new Error('分类结果未知') }
      return { ...classification(), name: file.name, classification_id: file.name }
    })
    const { wrapper, button } = await setup()
    const input = wrapper.get('input[type="file"][multiple]')
    Object.defineProperty(input.element, 'files', { value: ['process.xlsx', 'inspection.xlsx'].map(name => new File(['生产资料'], name)) })
    await input.trigger('change'); await flushPromises()
    const failedRequest = archive.archiveClassifyExcel.mock.calls[1][0] as FormData
    await button('重试未完成文件').trigger('click'); await flushPromises()
    expect(archive.archiveClassifyExcel.mock.calls.map(([form]) => (form.get('file') as File).name)).toEqual(['process.xlsx', 'inspection.xlsx', 'inspection.xlsx'])
    expect((archive.archiveClassifyExcel.mock.calls[2][0] as FormData).get('request_key')).toBe(failedRequest.get('request_key'))
    expect(legacy.upload).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('invalidates candidate saving when the confirmed fragment classification is edited', async () => {
    const { wrapper, choose, button } = await setup(); await choose()
    await button('确认分类并继续').trigger('click'); await flushPromises()
    await button('预览清理候选').trigger('click'); await flushPromises()
    await wrapper.findAll('.classification-region')[0].findAll('input[type="checkbox"]').find(input => input.element.closest('label')?.textContent?.trim() === '工艺')!.setValue(false)
    expect(button('预览清理候选').attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('button').some(item => item.text() === '保存所选模板')).toBe(false)
    expect(archive.saveReviewedExcel).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not publish a template refresh when saving is rejected', async () => {
    archive.saveReviewedExcel.mockRejectedValueOnce(new Error('模板保存被拒绝，未写入'))
    const { wrapper, choose, button } = await setup(); await choose()
    await button('确认分类并继续').trigger('click'); await flushPromises()
    await button('预览清理候选').trigger('click'); await flushPromises()
    await wrapper.findAll('input[type="checkbox"]').find(input => input.element.closest('label')?.textContent?.includes('发布清理后的文件'))!.setValue(true)
    const dispatch = vi.spyOn(window, 'dispatchEvent')
    await button('保存所选模板').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('模板保存被拒绝，未写入')
    expect(dispatch.mock.calls.some(([event]) => event.type === 'xcagi:templates-updated')).toBe(false)
    wrapper.unmount()
  })

  it('preserves an archived selection while opening the explicit history workspace', async () => {
    const { wrapper, choose, button } = await setup(); await choose()
    await button('历史导入任务').trigger('click'); await flushPromises()
    await vi.waitFor(() => expect(legacy.runs).toHaveBeenCalledTimes(1))
    expect(wrapper.find('.etl-dropzone').exists()).toBe(false)
    await button('原件归档与模板整理').trigger('click'); await flushPromises()
    expect(wrapper.findAll('.classification-region')).toHaveLength(3)
    expect(archive.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
