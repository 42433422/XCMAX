import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const { archive, legacy } = vi.hoisted(() => ({
  archive: {
    archiveClassifyExcel: vi.fn(),
    confirmClassification: vi.fn(),
    reviewExcel: vi.fn(),
    saveReviewedExcel: vi.fn(),
    archiveAssets: vi.fn(),
    refineReviewedExcel: vi.fn(),
  },
  legacy: {
    capabilities: vi.fn(), templates: vi.fn(), runs: vi.fn(), targetConfigs: vi.fn(),
    run: vi.fn(), upload: vi.fn(), preview: vi.fn(), execute: vi.fn(),
  },
}))
vi.mock('@/api/templatePreview', () => ({ default: archive }))
vi.mock('@/api/etl', () => ({ etlApi: legacy }))
vi.mock('@/api/auth', () => ({ authApi: { getCurrentUser: vi.fn().mockResolvedValue({ success: true, data: { permissions: ['etl.read'] } }) } }))
vi.mock('@/api/xcmaxMarketProxy', () => ({ default: { getPlatformDefaultModel: vi.fn().mockResolvedValue({ provider: '', model_id: '' }) } }))

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
  const EtlCenterView = (await import('./EtlCenterView.vue')).default
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
    const start = wrapper.findAll('button').find(item => item.text() === '开始处理')
    if (start) { await start.trigger('click'); await flushPromises() }
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

describe('data docking user-only intake', () => {
  it('keeps upload → A4 pick only and hides admin/classification UI', async () => {
    const { wrapper, choose } = await setup()
    expect(wrapper.find('.etl-admin-panel').exists()).toBe(false)
    expect(wrapper.find('.etl-composer__input').exists()).toBe(true)
    expect(wrapper.text()).toContain('上传文件，挑选模板')
    await choose()
    expect(archive.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    expect(archive.confirmClassification).toHaveBeenCalled()
    expect(archive.reviewExcel).toHaveBeenCalled()
    expect(wrapper.findAll('.classification-region')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('管理员与档案')
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(3)
    expect(wrapper.find('[aria-current="step"]')?.text()).toContain('选模板')
    expect(legacy.upload).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('auto-previews and saves the selected A4 candidate', async () => {
    const { wrapper, choose, button } = await setup(); await choose()
    expect((archive.reviewExcel.mock.calls[0][0] as FormData).get('region_range')).toBe('A1:D4')
    const dispatch = vi.spyOn(window, 'dispatchEvent')
    await wrapper.findAll('input[type="checkbox"]').find(input => input.element.closest('label')?.textContent?.includes('发布清理后的文件'))!.setValue(true)
    await button('保存所选模板').trigger('click'); await flushPromises()
    expect((archive.saveReviewedExcel.mock.calls[0][0] as FormData).get('review_id')).toBe('A1:D4')
    expect(dispatch.mock.calls.map(([e]) => e).filter(e => e.type === 'xcagi:templates-updated')).toHaveLength(1)
    wrapper.unmount()
  })

  it('accepts typed requirements in the bottom composer', async () => {
    const { wrapper, button } = await setup()
    await wrapper.get('.etl-composer__input').setValue('保留工艺表头')
    await wrapper.get('.etl-composer__send').trigger('click')
    expect(wrapper.text()).toContain('整理要求：保留工艺表头')
    const input = wrapper.get('input[type="file"][multiple]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [new File(['工艺'], '生产单.xlsx')] })
    await input.trigger('change'); await flushPromises()
    await button('开始处理').trigger('click'); await flushPromises()
    expect(archive.reviewExcel).toHaveBeenCalled()
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(3)
    wrapper.unmount()
  })

  it('keeps archive request identity when classification fails', async () => {
    archive.archiveClassifyExcel.mockRejectedValueOnce(new Error('分类结果未知'))
    const { wrapper, choose, button } = await setup(); await choose()
    expect(wrapper.text()).toContain('请先查看原件档案核对，勿重新选择文件重复上传')
    const first = archive.archiveClassifyExcel.mock.calls[0][0] as FormData
    await button('重试未完成文件').trigger('click'); await flushPromises()
    expect((archive.archiveClassifyExcel.mock.calls[1][0] as FormData).get('request_key')).toBe(first.get('request_key'))
    wrapper.unmount()
  })

  it('preserves intake while opening history workspace', async () => {
    const { wrapper, choose, button } = await setup(); await choose()
    await button('历史导入任务').trigger('click'); await flushPromises()
    await vi.waitFor(() => expect(legacy.runs).toHaveBeenCalledTimes(1))
    await button('导入').trigger('click'); await flushPromises()
    expect(wrapper.findAll('.reviewed-template__preview--a4').length).toBeGreaterThan(0)
    expect(archive.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('returns from history deep-link to intake', async () => {
    legacy.runs.mockResolvedValue([])
    const { wrapper, router, button } = await setup('run-42')
    expect(wrapper.find('button.active').text()).toContain('历史导入任务')
    await button('导入').trigger('click'); await flushPromises()
    expect(router.currentRoute.value.query.run_id).toBeUndefined()
    expect(wrapper.find('button.active').text()).toContain('导入')
    expect(wrapper.text()).toContain('上传 → 选模板')
    wrapper.unmount()
  })

  it('shows chatlike empty composer guidance', async () => {
    const { wrapper } = await setup()
    expect(wrapper.text()).toContain('上传文件，挑选模板')
    expect(wrapper.find('.etl-composer__input').exists()).toBe(true)
    expect(wrapper.find('.etl-admin-panel').exists()).toBe(false)
    expect(wrapper.find('.etl-composer__start').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('selects an A4 candidate card after auto preview', async () => {
    const { wrapper, choose } = await setup(); await choose()
    const cards = wrapper.findAll('.reviewed-template__preview--a4')
    expect(cards).toHaveLength(3)
    expect(cards[0].attributes('aria-selected')).toBe('true')
    await cards[2].trigger('click')
    expect(cards[2].attributes('aria-selected')).toBe('true')
    wrapper.unmount()
  })
})
