import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import ReviewedExcelTemplate from './ReviewedExcelTemplate.vue'
import type { useReviewedDocuments } from '@/composables/useReviewedDocuments'

const api = vi.hoisted(() => ({
  archiveClassifyExcel: vi.fn(), classifyExcel: vi.fn(), confirmClassification: vi.fn(),
  archiveQuota: vi.fn(), setArchiveQuota: vi.fn(), archiveAssets: vi.fn(), setArchiveAssetState: vi.fn(),
  downloadArchiveVersion: vi.fn(), recoverArchiveVersion: vi.fn(), appendArchiveVersion: vi.fn(),
  classifyArchiveVersion: vi.fn(), downloadClassificationSource: vi.fn(), downloadAutoSlice: vi.fn(),
  analyzeClassification: vi.fn(), autoSlices: vi.fn(), templateFamilies: vi.fn(), reviewExcel: vi.fn(),
  refineReviewedExcel: vi.fn(), previewReviewedIntake: vi.fn(), saveReviewedExcel: vi.fn(),
  reviewedExcelIdentity: vi.fn(), reviewedCandidateResult: vi.fn(), recentClassifications: vi.fn(),
  downloadReviewedExcel: vi.fn(), downloadReviewedCandidate: vi.fn(), recoverClassificationAnswer: vi.fn(),
}))
const elt = vi.hoisted(() => ({ run: vi.fn(), autoIngestProgress: vi.fn() }))
vi.mock('@/api/templatePreview', () => ({ default: api }))
vi.mock('@/api/elt', () => ({ eltApi: elt }))
vi.mock('@/api/xcmaxMarketProxy', () => ({ default: { llmResolveChatDefault: vi.fn().mockResolvedValue({ ok: true, provider: 'platform', model: 'default-chat' }) } }))

type Region = Record<string, unknown>
const region = (range: string, labels: string[] = ['unknown'], extra: Region = {}) => ({
  range, original_range: range, labels, checked_cells: 4, evidence: [], parent_heading: '', dependency_status: 'ready',
  needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [], ...extra,
})
const sheet = (regions: Region[], extra: Record<string, unknown> = {}) => ({
  sheet: 'Sheet1', sheet_state: 'visible', processable: true, labels: ['unknown'], checked_cells: 4, evidence: [], regions, ...extra,
})
function classification(name: string, sheets: ReturnType<typeof sheet>[]) {
  return { name, status: 'classified', classification_id: `class-${name}`, version: 'v1', model_status: 'not_called', confirmed: false, sheets }
}
const layout = (value: string) => [{ sheet: 'Sheet1', widths: [20], rows: [{ height: 20, cells: [{ cell: 'A1', value, formula: false, rowspan: 1, colspan: 1, bold: false, italic: false, font_size: 11, font_color: '', fill: '', align: 'left' }] }], truncated: false }]
function reviewedPayload(id = 'review-editing') {
  const candidates = [0, 1, 2].map(i => ({ id: `candidate-${i}`, label: `候选${i + 1}`, explanation: `清理候选${i + 1}`, clear: [{ sheet: 'Sheet1', cell: 'A2' }] }))
  return { review_id: id, sha256: 'synthetic-sha', cells: [], sheets: ['Sheet1'], layout: layout('原件'),
    proposal: { version: 'v1', parent_version: null, candidates, evidence: [], model: { status: 'returned' },
      result_previews: candidates.map(candidate => ({ candidate_id: candidate.id, sha256: candidate.id, layout: layout(candidate.label), layout_truncated: false })) } }
}
let wrapper: VueWrapper
let host: HTMLElement
const button = (text: string) => wrapper.findAll('button').find(el => el.text() === text)!
const state = () => wrapper.vm.$.setupState as Record<string, unknown>
const chips = () => wrapper.findAll('.elt-composer__chip')
const regions = () => wrapper.findAll('.classification-region')
const labelInput = (index: number, label: string) => {
  const entry = regions()[index].findAll('label').find(el => el.text() === label)!
  return entry.get('input[type=checkbox]')
}
const regionRadio = (index: number) => regions()[index].get('input[name="template-region"]')
async function stageFiles(names: string[]) {
  const input = wrapper.get('input[type=file]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: names.map(name => new File(['synthetic workbook'], name)) })
  await input.trigger('change')
}
async function start() { await button('开始处理').trigger('click'); await flushPromises() }
function mockClassifications(files: Record<string, unknown>) {
  api.archiveClassifyExcel.mockImplementation(async (form: FormData) => files[(form.get('file') as File).name])
}
beforeEach(() => {
  vi.resetAllMocks()
  updateProductReadAccountScope({ tenantId: 1, localUserId: 'editing-A', accountKind: 'local' })
  api.reviewedExcelIdentity.mockResolvedValue({ actor: '1:7' })
  api.recentClassifications.mockResolvedValue({ files: [] })
  api.reviewExcel.mockResolvedValue(reviewedPayload())
  api.autoSlices.mockResolvedValue({ slices: [] })
  api.templateFamilies.mockResolvedValue({ families: [] })
  api.analyzeClassification.mockImplementation(async (id: string) => {
    const found = api.archiveClassifyExcel.mock.results.map(result => result.value).find((entry?: { classification_id?: string }) => entry?.classification_id === id)
    return { version: 'model-v1', model_status: 'returned', sheets: found ? found.sheets : [sheet([region('A1:B2')])] }
  })
  host = document.createElement('div'); document.body.append(host)
  wrapper = mount(ReviewedExcelTemplate, { attachTo: host })
})
afterEach(() => { wrapper.unmount(); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('分类区域编辑', () => {
  it('定位区域、切换标签并把输入坐标规范化后同步所选区域', async () => {
    mockClassifications({
      'alpha.xlsx': classification('alpha.xlsx', [sheet([region('A1:B2', ['unknown']), region('D1:E4', ['unknown'])])]),
      'beta.xlsx': classification('beta.xlsx', [sheet([region('A10:B12', ['unknown'])])]),
    })
    await stageFiles(['alpha.xlsx', 'beta.xlsx']); await start()
    expect(regions()).toHaveLength(3)
    // 选择另一份文件的区域：先切换当前文件，再同步所选区域与名称
    await regionRadio(2).trigger('change'); await flushPromises()
    expect(wrapper.text()).toContain('所选区域：Sheet1 / A10:B12')
    // 给第二个区域打「报价」标签时移除 unknown；再勾选 unknown 时只保留 unknown
    await labelInput(1, '报价').setValue(true); await flushPromises()
    expect((labelInput(1, '报价').element as HTMLInputElement).checked).toBe(true)
    expect((labelInput(1, '未知/待理解').element as HTMLInputElement).checked).toBe(false)
    await labelInput(1, '未知/待理解').setValue(true); await flushPromises()
    expect((labelInput(1, '报价').element as HTMLInputElement).checked).toBe(false)
    expect((labelInput(1, '未知/待理解').element as HTMLInputElement).checked).toBe(true)
    // 取消最后一个标签时回退为未知，而不是留空
    await labelInput(1, '报价').setValue(false); await flushPromises()
    expect((labelInput(1, '未知/待理解').element as HTMLInputElement).checked).toBe(true)
    // 修改当前所选区域的坐标：小写与空格被规范化，并更新所选区域提示
    const rangeInput = regions()[2].get('details input')
    await rangeInput.setValue('a10 : b13'); await flushPromises()
    expect(wrapper.text()).toContain('所选区域：Sheet1 / A10:B13')
    // 非标准坐标保留用户输入以便服务端再次校验
    await rangeInput.setValue('待核对'); await flushPromises()
    expect((state().classifications as { sheets: { regions: { range: string }[] }[] }[])[1].sheets[0].regions[0].range).toBe('待核对')
  })

  it('批量设置标签后按核对结果撤回已失效的区域选择', async () => {
    mockClassifications({ 'alpha.xlsx': classification('alpha.xlsx', [sheet([region('A1:B2'), region('D1:E4')])]) })
    api.confirmClassification.mockImplementation(async () => ({
      version: 'v2', confirmed: false, sheets: [sheet([region('A7:B8'), region('D1:E4')])],
      message: '拆分已保存，请再次确认。',
    }))
    await stageFiles(['alpha.xlsx']); await start()
    await regions()[0].get('input[type=checkbox]').setValue(true)
    await regions()[1].get('input[type=checkbox]').setValue(true)
    await wrapper.get('select').setValue('quotation'); await flushPromises()
    await button('应用到选中区域').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('报价：alpha.xlsx / Sheet1 / A1:B2；alpha.xlsx / Sheet1 / D1:E4')
    expect((labelInput(0, '报价').element as HTMLInputElement).checked).toBe(true)
    await button('确认分类并继续').trigger('click'); await flushPromises()
    const form = api.confirmClassification.mock.calls[0][1] as FormData
    expect(JSON.parse(String(form.get('labels_json'))).map((entry: { labels: string[] }) => entry.labels)).toEqual([['quotation'], ['quotation']])
    expect(wrapper.text()).toContain('当前所选片段已变化，请从确认后的文档片段中重新选择')
    // 重新选择片段时会提示需要再次确认分类与续表关系
    await regionRadio(0).trigger('change'); await flushPromises()
    expect(wrapper.text()).toContain('已选择新的文档片段，请再次确认分类和续表关系后清理。')
    expect(wrapper.emitted('stage')?.some(([stage]) => stage === 'fragments')).toBe(true)
  })
})

describe('档案版本下载与入库状态', () => {
  it('下载原件版本并在读取失败时提示用户核对档案', async () => {
    api.archiveAssets.mockResolvedValue({ assets: [{ id: 'asset-1', name: '归档.xlsx', state: 'active', versions: [{ id: 'ver-1', version: 1, status: 'ready', sha256: 'a'.repeat(64), classification_id: null }] }] })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const createObjectURL = vi.fn(() => 'blob:archive'); vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL: vi.fn() })
    api.downloadArchiveVersion.mockResolvedValue({ blob: async () => new Blob(['synthetic']) })
    await button('查看原件档案').trigger('click'); await flushPromises()
    await button('下载原件版本').trigger('click'); await flushPromises()
    expect(api.downloadArchiveVersion).toHaveBeenCalledWith('ver-1')
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(click).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[role=alert]').exists()).toBe(false)
    api.downloadArchiveVersion.mockRejectedValueOnce(new Error('原件已隔离'))
    await button('下载原件版本').trigger('click'); await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toBe('原件已隔离')
  })

  it('保存模板后展示审批等待与真实入库进度', async () => {
    mockClassifications({ 'intake.xlsx': classification('intake.xlsx', [sheet([region('A1:B2')])]) })
    api.confirmClassification.mockResolvedValue({ version: 'v2', confirmed: true, sheets: [sheet([region('A1:B2')])] })
    elt.autoIngestProgress.mockResolvedValue({ status: 'running', kb_progress: { stage: 'embedding', pct: 40, message: '写入知识库', document_written: true, embedding_count: 2, rag_enabled: true }, business_progress: { stage: 'queued', pct: 0, message: '排队' } })
    api.previewReviewedIntake.mockResolvedValue({ intake: { run_id: 'run-intake', mod_id: '', candidate_sha256: 'candidate',
      knowledge: { action: 'new', documents: 1 }, business: { id: 'run-intake', target_type: 'knowledge', status: 'preview_ready', preview_revision: 'revision', summary: { new: 1, update: 0, skip: 0, error: 0 } } } })
    api.saveReviewedExcel.mockResolvedValue({ template_id: 'template-intake', auto_ingest: { success: true, batch_id: 'batch-intake', status: 'awaiting_approval' } })
    await stageFiles(['intake.xlsx']); await start()
    await button('确认分类并继续').trigger('click'); await flushPromises()
    await button('预览清理候选').trigger('click'); await flushPromises()
    expect(api.previewReviewedIntake).toHaveBeenCalled()
    await wrapper.findAll('input[type=checkbox]').find(input => input.element.closest('label')?.textContent?.includes('企业共享模板库'))!.setValue(true)
    await button('保存所选模板').trigger('click'); await flushPromises()
    const saved = api.saveReviewedExcel.mock.calls[0][0] as FormData
    expect(saved.get('publish_to_tenant')).toBe('true')
    expect(saved.get('review_id')).toBe('review-editing')
    expect(saved.get('intake_run_id')).toBe('run-intake')
    expect(wrapper.text()).toContain('已提交审批工作台')
    expect(wrapper.text()).toContain('batch-intake')
    expect(wrapper.text()).toContain('文档已写入')
    expect(wrapper.text()).toContain('向量索引 2')
    expect(elt.autoIngestProgress).toHaveBeenCalledWith('batch-intake')
    expect(wrapper.get('[aria-label="自动入库真实进度"]').text()).toContain('排队')
  })
})

describe('批量追加与拖拽上传边界', () => {
  it('追加文件时忽略不可导入项，并在超过 200 个文件时停止', async () => {
    mockClassifications(Object.fromEntries(Array.from({ length: 200 }, (_, index) => [`batch-${index}.xlsx`, classification(`batch-${index}.xlsx`, [sheet([region('A1:B2')])])])))
    await stageFiles(Array.from({ length: 200 }, (_, index) => `batch-${index}.xlsx`)); await start()
    expect(chips()).toHaveLength(200)
    // 追加不支持的格式：不改变本批文件，也不显示新错误
    const input = wrapper.get('input[type=file]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [new File(['synthetic'], 'notes.txt')] })
    await input.trigger('change'); await flushPromises()
    expect(chips()).toHaveLength(200)
    expect(wrapper.find('[role=alert]').exists()).toBe(false)
    // 再追加一份 Excel 时超过单批上限
    Object.defineProperty(input.element, 'files', { configurable: true, value: [new File(['synthetic'], 'extra.xlsx')] })
    await input.trigger('change'); await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('一次最多上传 200 个文件')
    expect(chips()).toHaveLength(200)
  })

  it('选择整批超过 50 MB 的文件时清空本批并提示分批上传', async () => {
    const files = ['big-a.xlsx', 'big-b.xlsx'].map(name => {
      const file = new File(['synthetic'], name)
      Object.defineProperty(file, 'size', { value: 30 * 1024 * 1024 })
      return file
    })
    const input = wrapper.get('input[type=file]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: files })
    await input.trigger('change'); await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('本批文件超过 50 MB')
    expect(chips()).toHaveLength(0)
    expect(api.archiveClassifyExcel).not.toHaveBeenCalled()
  })

  it('文件夹为空或读取失败时给出可执行提示', async () => {
    const input = wrapper.get('input[type=file]')
    input.element.setAttribute('webkitdirectory', '')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [] })
    await input.trigger('change'); await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('文件夹是空的或没有可读取的文件')
    const composer = wrapper.get('.elt-composer')
    await composer.trigger('drop', { dataTransfer: { items: [{ webkitGetAsEntry: () => ({ isDirectory: true, isFile: false, createReader: () => ({ readEntries: (resolve: (entries: unknown[]) => void) => resolve([]) }) }) }], files: [] } })
    await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('文件夹是空的或没有可读取的文件')
    await composer.trigger('drop', { dataTransfer: { items: [{ webkitGetAsEntry: () => ({ isFile: true, isDirectory: false, file: (_ok: unknown, fail: (error: Error) => void) => fail(new Error('unreadable')) }) }], files: [] } })
    await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('请拖入 Excel 或对账单 Word')
    const brokenFile = { isFile: true, isDirectory: false, file: (_ok: unknown, fail: (error: Error) => void) => fail(new Error('unreadable')) }
    const brokenDirectory = { isDirectory: true, isFile: false, createReader: () => ({ readEntries: (resolve: (entries: unknown[]) => void) => resolve([brokenFile]) }) }
    await composer.trigger('drop', { dataTransfer: { items: [{ webkitGetAsEntry: () => brokenDirectory }], files: [] } })
    await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('文件夹没有读完')
  })

  it('拖入整个文件夹时逐个读取文件并开始分类', async () => {
    mockClassifications({ 'nested.xlsx': classification('nested.xlsx', [sheet([region('A1:B2')])]) })
    const fileEntry = { isFile: true, isDirectory: false, file: (resolve: (file: File) => void) => resolve(new File(['synthetic'], 'nested.xlsx')) }
    let first = true
    const directory = { isDirectory: true, isFile: false, createReader: () => ({ readEntries: (resolve: (entries: unknown[]) => void) => { resolve(first ? [fileEntry] : []); first = false } }) }
    await wrapper.get('.elt-composer').trigger('drop', { dataTransfer: { items: [{ webkitGetAsEntry: () => directory }], files: [] } })
    await flushPromises(); await start()
    expect(chips()).toHaveLength(1)
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    expect(regions()).toHaveLength(1)
  })
})

describe('整理要求与重试路径', () => {
  it('没有文件时先把整理要求留在对话中，选择文件后再处理', async () => {
    await wrapper.get('.elt-composer__input').setValue('保留客户栏')
    await button('发送').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('整理要求：保留客户栏')
    expect((wrapper.get('.elt-composer__input').element as HTMLTextAreaElement).value).toBe('')
    expect(api.archiveClassifyExcel).not.toHaveBeenCalled()
    await wrapper.get('.elt-composer__input').setValue('清理空白行')
    await button('发送').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('整理要求：清理空白行')
    expect(api.archiveClassifyExcel).not.toHaveBeenCalled()
  })

  it('开始处理时携带整理要求并在处理过程中显示进度', async () => {
    mockClassifications({ 'alpha.xlsx': classification('alpha.xlsx', [sheet([region('A1:B2')])]) })
    await stageFiles(['alpha.xlsx'])
    await wrapper.get('.elt-composer__input').setValue('保留表头')
    await start()
    expect(wrapper.text()).toContain('整理要求：保留表头')
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('原件已归档并完成规则预筛')
  })

  it('读取已保存分类失败时提示并保持当前文件不变', async () => {
    api.recentClassifications.mockRejectedValueOnce(new Error('分类记录服务不可用'))
    await button('查看已保存分类').trigger('click'); await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toBe('分类记录服务不可用')
    expect(chips()).toHaveLength(0)
  })

  it('按所选区域预演候选，并允许把打印范围改成所选片段后重新生成', async () => {
    mockClassifications({ 'alpha.xlsx': classification('alpha.xlsx', [sheet([region('A1:B2')])]) })
    api.confirmClassification.mockResolvedValue({ version: 'v2', confirmed: true, sheets: [sheet([region('A1:B2')])] })
    await stageFiles(['alpha.xlsx']); await start()
    await button('确认分类并继续').trigger('click'); await flushPromises()
    await button('预览清理候选').trigger('click'); await flushPromises()
    const first = api.reviewExcel.mock.calls[0][0] as FormData
    expect(first.get('classification_id')).toBe('class-alpha.xlsx')
    expect(first.get('region_sheet')).toBe('Sheet1')
    expect(first.get('region_range')).toBe('A1:B2')
    expect(first.get('print_area_mode')).toBe('source')
    expect(wrapper.text()).toContain('模板 1：候选1')
    await wrapper.findAll('input[type=checkbox]').find(input => input.element.closest('label')?.textContent?.includes('打印范围'))!.setValue(true)
    await button('预览清理候选').trigger('click'); await flushPromises()
    expect((api.reviewExcel.mock.calls[1][0] as FormData).get('print_area_mode')).toBe('selected')
    expect(wrapper.emitted('stage')?.some(([stage]) => stage === 'template')).toBe(true)
  })

  it('Word 原件先取回转换后的工作簿再生成候选，失败时展示后端原因', async () => {
    mockClassifications({ 'report.docx': classification('report.docx', [sheet([region('A1:B2')])]) })
    api.confirmClassification.mockResolvedValue({ version: 'v2', confirmed: true, sheets: [sheet([region('A1:B2')])] })
    api.downloadClassificationSource.mockResolvedValue({ blob: async () => new Blob(['converted workbook']) })
    await stageFiles(['report.docx']); await start()
    await button('确认分类并继续').trigger('click'); await flushPromises()
    await button('预览清理候选').trigger('click'); await flushPromises()
    expect(api.downloadClassificationSource).toHaveBeenCalledWith('class-report.docx')
    const converted = (api.reviewExcel.mock.calls[0][0] as FormData).get('file') as File
    expect(converted.name).toBe('report.xlsx')
    expect(converted.type).toBe('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    api.reviewExcel.mockRejectedValueOnce(new Error('模型连接异常：请重新登录'))
    await button('预览清理候选').trigger('click'); await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toBe('模型连接异常：请重新登录')
    expect(wrapper.text()).not.toContain('模板 1：候选1')
  })
})

describe('旧版 XLS 与选择入口', () => {
  it('旧版 XLS 先确认有限用途转换再上传', async () => {
    Object.defineProperty(File.prototype, 'arrayBuffer', { configurable: true, value: async () => new Uint8Array([1]).buffer })
    vi.spyOn(globalThis.crypto.subtle, 'digest').mockResolvedValue(new Uint8Array(32).fill(0x0a).buffer as ArrayBuffer)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockClassifications({ 'legacy.xls': classification('legacy.xls', [sheet([region('A1:B2')])]) })
    await stageFiles(['legacy.xls']); await start()
    const form = api.archiveClassifyExcel.mock.calls[0][0] as FormData
    expect(form.get('legacy_test_only')).toBe('true')
    expect(form.get('legacy_source_sha256')).toBe('0a'.repeat(32))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('legacy.xls'))
    expect(regions()).toHaveLength(1)
    delete (File.prototype as unknown as Record<string, unknown>).arrayBuffer
  })

  it('取消旧 XLS 有限用途转换后不上传并明确提示', async () => {
    Object.defineProperty(File.prototype, 'arrayBuffer', { configurable: true, value: async () => new Uint8Array([1]).buffer })
    vi.spyOn(globalThis.crypto.subtle, 'digest').mockResolvedValue(new Uint8Array(32).fill(0x0b).buffer as ArrayBuffer)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    mockClassifications({ 'legacy.xls': classification('legacy.xls', [sheet([region('A1:B2')])]) })
    await stageFiles(['legacy.xls']); await start()
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('legacy.xls'))
    expect(api.archiveClassifyExcel).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('已取消旧 XLS 有限用途转换；未上传。')
    delete (File.prototype as unknown as Record<string, unknown>).arrayBuffer
  })

  it('整文件夹选择里没有可导入文件时提示文件夹内容', async () => {
    const input = wrapper.get('input[type=file]')
    input.element.setAttribute('webkitdirectory', '')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [new File(['synthetic'], 'readme.txt')] })
    await input.trigger('change'); await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toBe('文件夹里没有 Excel 或对账单 Word（.xlsx / .xls / .docx）')
    expect(input.element.hasAttribute('webkitdirectory')).toBe(false)
  })
})

describe('模型切片与候选核对', () => {
  const slice = { index: 0, basis: 'model_group', confirmed: false, sha256: 'slice-0', filename: '单据A.xlsx', display_name: '单据A', fragments: [{ sheet: 'Sheet1', range: 'A1:B2' }] }

  it('加载模型切片后可下载裁切件并只用该单据生成候选', async () => {
    mockClassifications({ 'alpha.xlsx': classification('alpha.xlsx', [sheet([region('A1:B2', ['template'], { evidence: [{ cell: 'A1', matched: '模板' }], header_cells: [{ cell: 'A1', value: '标题' }], possible_shared_context: [{ sheet: 'Sheet1', cell: 'F1' }] })])]) })
    api.autoSlices.mockResolvedValue({ slices: [slice] })
    api.downloadAutoSlice.mockResolvedValue({ blob: async () => new Blob(['slice workbook']) })
    const createObjectURL = vi.fn(() => 'blob:slice'); vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL: vi.fn() })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    await stageFiles(['alpha.xlsx']); await start()
    expect(wrapper.text()).toContain('依据：A1「模板」')
    expect(wrapper.text()).toContain('可能的图例或说明：F1')
    await button('模型分析已分类文件').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('使用当前账号的模型配置')
    expect(wrapper.text()).toContain('（模型建议同一单据）')
    await button('下载裁切 Excel').trigger('click'); await flushPromises()
    expect(api.downloadAutoSlice).toHaveBeenCalledWith('class-alpha.xlsx', 'model-v1', 0)
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    api.downloadAutoSlice.mockRejectedValueOnce(new Error('裁切件已过期'))
    await button('下载裁切 Excel').trigger('click'); await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toBe('裁切件已过期')
    await button('用此单据生成模板').trigger('click'); await flushPromises()
    const form = api.reviewExcel.mock.calls[0][0] as FormData
    expect(form.get('classification_id')).toBe('class-alpha.xlsx')
    expect(form.get('classification_version')).toBe('model-v1')
    expect(form.get('auto_slice_index')).toBe('0')
    expect(form.get('print_area_mode')).toBeNull()
    expect(wrapper.text()).toContain('模板 1：候选1')
  })

  it('放大预览候选并选择后，下载候选差异失败时保留错误提示', async () => {
    mockClassifications({ 'alpha.xlsx': classification('alpha.xlsx', [sheet([region('A1:B2')])]) })
    api.confirmClassification.mockResolvedValue({ version: 'v2', confirmed: true, sheets: [sheet([region('A1:B2')])] })
    await stageFiles(['alpha.xlsx']); await start()
    await button('确认分类并继续').trigger('click'); await flushPromises()
    await button('预览清理候选').trigger('click'); await flushPromises()
    const cards = wrapper.findAll('.reviewed-template__preview--capsule')
    expect(cards).toHaveLength(3)
    await cards[1].get('button.reviewed-template__a4-open').trigger('click'); await flushPromises()
    const dialog = document.body.querySelector('.template-preview-dialog') as HTMLElement
    expect(dialog.getAttribute('aria-label')).toContain('模板 2')
    const select = Array.from(dialog.querySelectorAll('button')).find(el => el.textContent === '选择此模板') as HTMLButtonElement
    select.click(); await flushPromises()
    expect(state().candidateIndex).toBe(1)
    expect(cards[1].classes()).toContain('reviewed-template__preview--selected')
    api.downloadReviewedCandidate.mockRejectedValueOnce(new Error('候选已失效'))
    await button('下载候选核对').trigger('click'); await flushPromises()
    expect(api.downloadReviewedCandidate).toHaveBeenCalledWith('review-editing', 'v1', 'candidate-0')
    expect(wrapper.get('[role=alert]').text()).toBe('候选已失效')
  })

  it('分类缺少来源版本时模型分析直接提示重新分类', async () => {
    mockClassifications({ 'nosource.xlsx': { ...classification('nosource.xlsx', [sheet([region('A1:B2')])]), classification_id: undefined, version: undefined } })
    await stageFiles(['nosource.xlsx']); await start()
    await button('模型分析已分类文件').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('分类来源或版本缺失，请重新分类')
    expect(api.analyzeClassification).not.toHaveBeenCalled()
  })

  it('自然语言修改建议生成新版本并锁定旧版本的保存', async () => {
    mockClassifications({ 'alpha.xlsx': classification('alpha.xlsx', [sheet([region('A1:B2')])]) })
    api.confirmClassification.mockResolvedValue({ version: 'v2', confirmed: true, sheets: [sheet([region('A1:B2')])] })
    api.refineReviewedExcel.mockResolvedValue({ proposal: { ...reviewedPayload().proposal, version: 'v2' } })
    await stageFiles(['alpha.xlsx']); await start()
    await button('确认分类并继续').trigger('click'); await flushPromises()
    await button('预览清理候选').trigger('click'); await flushPromises()
    await wrapper.get('input[placeholder="例如：保留客户信息，清理产品明细"]').setValue('保留客户信息')
    await button('生成新一轮三个模板').trigger('click'); await flushPromises()
    const form = api.refineReviewedExcel.mock.calls[0][0] as FormData
    expect(form.get('feedback')).toBe('保留客户信息')
    expect(form.get('parent_version')).toBe('v1')
    expect(wrapper.text()).toContain('服务端保留 2 个提案版本')
    await button('查看版本 1').trigger('click'); await flushPromises()
    expect(state().selectedVersion).toBe(0)
    expect(button('保存所选模板').attributes('disabled')).toBeDefined()
  })
})

describe('保存与下载回执', () => {
  it('保存时携带整理要求与复用信息，并允许下载清理后的模板', async () => {
    mockClassifications({ 'alpha.xlsx': classification('alpha.xlsx', [sheet([region('A1:B2')])]) })
    api.confirmClassification.mockResolvedValue({ version: 'v2', confirmed: true, sheets: [sheet([region('A1:B2')])] })
    api.previewReviewedIntake.mockResolvedValue({ intake: { run_id: 'run-save', mod_id: '', candidate_sha256: 'candidate', knowledge: { action: 'new', documents: 1 }, business: { id: 'run-save', target_type: 'knowledge', status: 'preview_ready', preview_revision: 'revision', summary: { new: 1, update: 0, skip: 0, error: 0 } } } })
    api.saveReviewedExcel.mockResolvedValue({ template_id: 'template-saved', reused: true, auto_ingest: { success: false, error: 'outcome_unknown' } })
    const createObjectURL = vi.fn(() => 'blob:template'); vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL: vi.fn() })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    await stageFiles(['alpha.xlsx'])
    await wrapper.get('.elt-composer__input').setValue('保留客户栏')
    await start()
    await button('确认分类并继续').trigger('click'); await flushPromises()
    await button('预览清理候选').trigger('click'); await flushPromises()
    await wrapper.findAll('input[type=checkbox]').find(input => input.element.closest('label')?.textContent?.includes('企业共享模板库'))!.setValue(true)
    await button('保存所选模板').trigger('click'); await flushPromises()
    const form = api.saveReviewedExcel.mock.calls[0][0] as FormData
    expect(form.get('composer_note')).toBe('保留客户栏')
    expect(form.get('intake_run_id')).toBe('run-save')
    expect(form.get('candidate_id')).toBe('candidate-0')
    expect(wrapper.text()).toContain('模板库里已有相同版式，沿用那一份。')
    expect(wrapper.text()).toContain('模板已保存，入库回执尚未确认')
    api.downloadReviewedExcel.mockResolvedValue({ blob: async () => new Blob(['template workbook']) })
    await button('下载清理后的模板').trigger('click'); await flushPromises()
    expect(api.downloadReviewedExcel).toHaveBeenCalledWith('template-saved')
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    api.downloadReviewedExcel.mockRejectedValueOnce(new Error('模板已删除'))
    await button('下载清理后的模板').trigger('click'); await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toBe('模板已删除')
  })

  it('从已保存分类恢复归档版本，并在文件哈希不一致时拒绝继续', async () => {
    Object.defineProperty(File.prototype, 'arrayBuffer', { configurable: true, value: async () => new Uint8Array([1, 2, 3]).buffer })
    const digest = vi.fn(async () => new Uint8Array(32).fill(0xbb).buffer)
    vi.spyOn(globalThis.crypto.subtle, 'digest').mockImplementation(digest)
    const sha = 'aa'.repeat(32)
    api.recentClassifications.mockResolvedValue({ files: [{ name: '归档.xlsx', sha256: sha, archive_version_id: 'ver-recent', classification_id: 'class-recent', latest: { version: 'v9', model_status: 'not_called', confirmed: true, sheets: [sheet([region('A1:B2')])] } }] })
    api.downloadClassificationSource.mockResolvedValue({ blob: async () => new Blob(['archived workbook']) })
    await button('查看已保存分类').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain(`归档.xlsx · ${sha}`)
    await button('恢复此分类并继续').trigger('click'); await flushPromises()
    expect(api.downloadClassificationSource).toHaveBeenCalledWith('class-recent')
    expect(wrapper.get('[role=alert]').text()).toBe('所选文件与分类来源不一致')
    digest.mockResolvedValue(new Uint8Array(32).fill(0xaa).buffer as ArrayBuffer)
    await button('恢复此分类并继续').trigger('click'); await flushPromises()
    expect(chips()).toHaveLength(1)
    expect(wrapper.text()).toContain('归档.xlsx')
    delete (File.prototype as unknown as Record<string, unknown>).arrayBuffer
  })
})

describe('分析失败与人工核对', () => {
  it('模型分析失败时标记结果未知并提示核对已保存分类', async () => {
    mockClassifications({ 'alpha.xlsx': classification('alpha.xlsx', [sheet([region('A1:B2')])]) })
    api.analyzeClassification.mockRejectedValueOnce(new Error('模型网关超时'))
    api.recentClassifications.mockResolvedValue({ files: [{ name: 'alpha.xlsx', sha256: '', classification_id: '', latest: null }] })
    await stageFiles(['alpha.xlsx']); await start()
    await button('模型分析已分类文件').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('分析失败：模型网关超时；请求结果可能未知，请查看已保存分类核对，勿重复发送')
    expect(wrapper.text()).toContain('部分请求结果未知，不可重发，需人工核对')
    expect(api.recentClassifications).toHaveBeenCalled()
  })

  it('档案模式下可核验已保存的模型回答而不重复调用模型', async () => {
    wrapper.unmount(); wrapper = mount(ReviewedExcelTemplate, { attachTo: host, props: { archiveOnSelect: true } })
    await stageFiles(['alpha.xlsx'])
    const checkpoint = { phase: 'failed', version: 'v1', completed: 1, total: 2, max_calls: 3, message: '批次中断' }
    state().classifications = [{ ...classification('alpha.xlsx', [sheet([region('A1:B2')])]), checkpoint }]
    ;(state().selectFile as (index: number) => void)(0)
    await wrapper.vm.$nextTick(); await flushPromises()
    api.recoverClassificationAnswer.mockRejectedValueOnce(new Error('保存的回答已过期'))
    await button('核验已保存回答').trigger('click'); await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toBe('保存的回答已过期')
    api.recoverClassificationAnswer.mockResolvedValueOnce({ checkpoint: { ...checkpoint, phase: 'ready', completed: 2 }, can_slice: false })
    await button('核验已保存回答').trigger('click'); await flushPromises()
    const form = api.recoverClassificationAnswer.mock.calls[0][1] as FormData
    expect(api.recoverClassificationAnswer.mock.calls[0][0]).toBe('class-alpha.xlsx')
    expect(form.get('version')).toBe('v1')
    expect(wrapper.text()).toContain('已核验保存的回答，完成 2/2 批；未重新调用模型。模型表示不能自动切片，需人工核对。')
    expect(button('核验已保存回答')).toBeUndefined()
  })

  it('渲染模型分组建议、片段关联与覆盖率核对信息', async () => {
    const linked = classification('alpha.xlsx', [sheet([region('A1:B2', ['template'])])])
    const linkedSheet = linked.sheets[0]
    linked.sheets[0] = { ...linkedSheet, checked_cells: 120, coverage: undefined } as typeof linkedSheet
    const withMeta = {
      ...linked, model_status: 'returned', suggested_documents: [{ document_id: 'doc-1', fragments: [{ sheet: 'Sheet1', range: 'A1:B2' }, { sheet: 'Sheet1', range: 'D1:E2' }] }],
      confirmed_document_count: 1,
      fragment_links: { items: [{ sheet: 'Sheet1', first: 'A1:B2', second: 'D1:E2', status: 'candidate', selected: false, model_group_suggested: true, repeated_header_observed: true, shared_dependencies: [{ sheet: 'Sheet1', cell: 'F1' }] }], omitted: 2 },
      budget: { calls: 2, max_calls: 6, unread: 8 },
      coverage: [{ sheet: 'Sheet1', sent: 100, total: 120, unread: ['A9'], value_truncated: ['C3'], deferred_large_values: ['D4'], unassigned: ['E5'], merged_omitted: 1, deferred_oversized_rows: [{ row: 9 }], model_unassigned: ['F9'] }],
      checkpoint: { phase: 'paused', version: 'v1', completed: 2, total: 4, max_calls: 6, calls_in_round: 2, message: '本轮预算已用完' },
    }
    mockClassifications({ 'alpha.xlsx': withMeta })
    await stageFiles(['alpha.xlsx']); await start()
    const text = wrapper.text()
    expect(text).toContain('模型分组建议 doc-1：Sheet1!A1:B2、Sheet1!D1:E2；仅供核对，未确认。')
    expect(text).toContain('已确认 1 个逻辑文档。')
    expect(text).toContain('同一文档 Sheet1：A1:B2 ↔ D1:E2；模型建议同组；观察到重复表头；模型共同引用 Sheet1!F1；关联仍待确认。')
    expect(text).toContain('还有 2 条候选未展示。')
    expect(text).toContain('已调用 2 次（每轮上限 6 次）；尚有 8 格未发送。')
    expect(text).toContain('Sheet1：发送 100/120 格；未发送 1 格，未归入区域 1 格，合并范围未发送 1 个，仍待确认。')
    expect(wrapper.text()).toContain('批次 2/4；本轮 2/6 次')
  })

  it('保存失败时提示核对模板库且不显示已保存状态', async () => {
    mockClassifications({ 'alpha.xlsx': classification('alpha.xlsx', [sheet([region('A1:B2')])]) })
    api.confirmClassification.mockResolvedValue({ version: 'v2', confirmed: true, sheets: [sheet([region('A1:B2')])] })
    api.previewReviewedIntake.mockResolvedValue({ intake: { run_id: 'run-fail', mod_id: '', candidate_sha256: 'candidate', knowledge: { action: 'new', documents: 1 }, business: { id: 'run-fail', target_type: 'knowledge', status: 'preview_ready', preview_revision: 'revision', summary: { new: 1, update: 0, skip: 0, error: 0 } } } })
    api.saveReviewedExcel.mockRejectedValueOnce(new Error('模板写入超时'))
    await stageFiles(['alpha.xlsx']); await start()
    await button('确认分类并继续').trigger('click'); await flushPromises()
    await button('预览清理候选').trigger('click'); await flushPromises()
    await wrapper.findAll('input[type=checkbox]').find(input => input.element.closest('label')?.textContent?.includes('企业共享模板库'))!.setValue(true)
    await button('保存所选模板').trigger('click'); await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toBe('模板写入超时；如果结果未知，请先核对模板库和分类记录，勿重复提交。')
    expect(wrapper.text()).not.toContain('下载清理后的模板')
  })
})

describe('档案文档处理', () => {
  it('单据候选生成失败后可重新生成、核对未知结果并放大只读原件', async () => {
    wrapper.unmount(); wrapper = mount(ReviewedExcelTemplate, { attachTo: host, props: { archiveOnSelect: true } })
    const file = new File(['synthetic'], 'archive.xlsx')
    const input = wrapper.get('input[type=file]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change'); await flushPromises()
    const workspace = state().documentWorkspace as ReturnType<typeof useReviewedDocuments>
    const doc = workspace.register('class-doc', 'v1', { index: 0, basis: 'model_group', confirmed: false, sha256: 'sha-doc', filename: '单据.xlsx', display_name: '单据', fragments: [{ sheet: 'Sheet1', range: 'A1:B2' }] }, file)
    doc.error = '模型连接异常'; await flushPromises()
    await wrapper.get('[data-document-key]').trigger('click'); await flushPromises()
    await button('重新生成候选').trigger('click'); await flushPromises()
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    expect(doc.review?.review_id).toBe('review-editing')
    const original = wrapper.findAll('.reviewed-template__preview--a4').find(card => card.text().includes('原件（只读）'))!
    await original.get('button.reviewed-template__a4-open').trigger('click'); await flushPromises()
    expect(document.body.querySelector('.template-preview-dialog')?.getAttribute('aria-label')).toContain('原件（只读）')
    await wrapper.findAll('.reviewed-template__select-candidate')[0].trigger('click'); await flushPromises()
    expect(doc.candidateIndex).toBe(0)
    // 结果未知时打开单据会先自动核对，仍可直接点击核对按钮
    doc.review = null; doc.unknown = true; doc.error = ''
    api.reviewedCandidateResult.mockRejectedValue(new Error('候选结果暂不可读'))
    await wrapper.get('[data-document-key]').trigger('click'); await flushPromises()
    await button('核对候选结果').trigger('click'); await flushPromises()
    expect(api.reviewedCandidateResult).toHaveBeenCalledTimes(2)
  })
})
