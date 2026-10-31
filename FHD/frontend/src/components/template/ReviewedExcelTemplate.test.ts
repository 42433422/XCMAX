import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
const api = vi.hoisted(() => ({ classifyExcel: vi.fn(), archiveClassifyExcel: vi.fn(), archiveQuota: vi.fn(), setArchiveQuota: vi.fn(), archiveAssets: vi.fn(), classifyArchiveVersion: vi.fn(), downloadArchiveVersion: vi.fn(), downloadClassificationSource: vi.fn(), setArchiveAssetState: vi.fn(), confirmClassification: vi.fn().mockResolvedValue({ version: "confirmed-version", confirmed: true }), analyzeClassification: vi.fn(), recentClassifications: vi.fn(), autoSlices: vi.fn(), reviewExcel: vi.fn(), refineReviewedExcel: vi.fn(), saveReviewedExcel: vi.fn(), downloadReviewedExcel: vi.fn(), downloadReviewedCandidate: vi.fn() }))
const etl = vi.hoisted(() => ({ autoIngestProgress: vi.fn(), autoIngestBatches: vi.fn(), withdrawAutoIngestBatch: vi.fn() }))
vi.mock('@/api/templatePreview', () => ({ default: api }))
vi.mock('@/api/elt', () => ({ eltApi: etl }))
vi.mock('@/api/xcmaxMarketProxy', () => ({
  default: {
    llmResolveChatDefault: vi.fn().mockResolvedValue({ ok: true, provider: 'platform', model: 'default-chat' }),
  },
}))
import ReviewedExcelTemplate from './ReviewedExcelTemplate.vue'
const layout = (value: string) => [{ sheet: '报价', widths: [20], rows: [{ height: 20, cells: [{ cell: 'B2', value, formula: false, rowspan: 1, colspan: 1, bold: false, italic: false, font_size: 11, font_color: '', fill: '', align: 'left' }] }], truncated: false }]
const candidates = [
  { id: 'preserve', label: '保留', explanation: '保留待确认', clear: [] },
  { id: 'table', label: '模板二', explanation: '清理实例', clear: [{ sheet: '报价', cell: 'B2' }] },
  { id: 'identity', label: '模板三', explanation: '清理更多', clear: [{ sheet: '报价', cell: 'B2' }] },
]
const proposal = (version: string) => ({ version, parent_version: null, candidates, evidence: [], model: { status: 'not_called' }, result_previews: candidates.map((c, i) => ({ candidate_id: c.id, sha256: String(i), layout: layout(i ? '' : '客户甲'), layout_truncated: false })) })
describe('reviewed Excel template', () => {
  beforeEach(() => {
    api.archiveClassifyExcel.mockReset().mockImplementation(async (form: FormData) => {
      const response = await api.classifyExcel(form)
      const file = form.get('file') as File
      return response.files.find((entry: { name: string }) => entry.name === file.name) || response.files[0]
    })
    api.confirmClassification.mockReset().mockImplementation(async (id: string, form: FormData) => {
      const response = await api.classifyExcel.mock.results.at(-1)!.value
      const item = response.files.find((entry: { classification_id: string }) => entry.classification_id === id)
      const sheets = JSON.parse(JSON.stringify(item.sheets))
      const edits = JSON.parse(String(form.get('labels_json')))
      for (const sheet of sheets) for (const region of sheet.regions) {
        const edit = edits.find((entry: { sheet: string; original_range: string }) => entry.sheet === sheet.sheet && entry.original_range === region.range)
        if (edit) { region.labels = edit.labels; region.range = edit.range }
      }
      return { version: 'confirmed-version', confirmed: true, sheets }
    })
  })
  it('offers legacy XLS through the archive conversion boundary in chatlike intake', () => {
    const archived = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    expect(archived.find('input[type=file]').attributes('accept')).toBe('.xlsx,.xls')
    expect(archived.find('.etl-admin-panel').exists()).toBe(false)
    expect(archived.find('.etl-composer__input').exists()).toBe(true)
    expect(archived.text()).toContain('上传文件，挑选模板')
    expect(archived.text()).not.toContain('管理员与档案')
    archived.unmount()
  })
  it.each([false, true])('binds limited XLS consent to the exact file hash (accepted=%s)', async accepted => {
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(accepted)
    vi.stubGlobal('crypto', { randomUUID: () => 'legacy-test-key', subtle: { digest: vi.fn().mockResolvedValue(new Uint8Array(32).fill(7).buffer) } })
    api.archiveClassifyExcel.mockReset().mockResolvedValue({ name: 'sample.xlsx', status: 'classified', classification_id: 'legacy-c', version: 'v1', sheets: [], usage_restrictions: ['打印版式未验证'] })
    const wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    try {
      const file = new File(['source'], 'sample.xls')
      Object.defineProperty(file, 'arrayBuffer', { value: async () => new Uint8Array([1, 2, 3]).buffer })
      const input = wrapper.find('input[type=file]'); Object.defineProperty(input.element, 'files', { value: [file] })
      await input.trigger('change'); await flushPromises()
      await wrapper.findAll('button').find(b => b.text() === '开始处理')!.trigger('click'); await flushPromises()
      expect(confirmation).toHaveBeenCalledTimes(1)
      expect(confirmation.mock.calls[0][0]).toContain('仅数据/模板测试；打印版式未验证，不可发布企业模板库')
      expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(accepted ? 1 : 0)
      if (accepted) {
        const form = api.archiveClassifyExcel.mock.calls[0][0] as FormData
        expect(form.get('legacy_test_only')).toBe('true')
        expect(form.get('legacy_source_sha256')).toBe('07'.repeat(32))
      } else expect(wrapper.text()).toContain('已取消旧 XLS 有限用途转换；未上传')
    } finally { wrapper.unmount(); confirmation.mockRestore(); vi.unstubAllGlobals() }
  })
  it('does not prompt or upload after the legacy hash operation becomes stale', async () => {
    let finish!: (value: ArrayBuffer) => void
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('crypto', { randomUUID: () => 'stale-key', subtle: { digest: () => new Promise<ArrayBuffer>(resolve => { finish = resolve }) } })
    api.archiveClassifyExcel.mockReset()
    const wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    try {
      const file = new File(['source'], 'stale.xls')
      Object.defineProperty(file, 'arrayBuffer', { value: async () => new ArrayBuffer(1) })
      const input = wrapper.find('input[type=file]'); Object.defineProperty(input.element, 'files', { value: [file] })
      await input.trigger('change'); await flushPromises()
      const start = wrapper.findAll('button').find(b => b.text() === '开始处理')!
      const pending = start.trigger('click')
      await flushPromises()
      wrapper.unmount()
      finish(new Uint8Array(32).buffer); await flushPromises(); await pending.catch(() => undefined)
      expect(confirmation).not.toHaveBeenCalled(); expect(api.archiveClassifyExcel).not.toHaveBeenCalled()
    } finally { confirmation.mockRestore(); vi.unstubAllGlobals() }
  })
  it.each(['receipt', 'xlsx-marker'])('blocks publishing limited-use %s while keeping preview and downloads available', async kind => {
    const wrapper = mount(ReviewedExcelTemplate)
    const state = wrapper.vm.$.setupState as Record<string, unknown>
    const file = new File(['derived'], 'test-only.xlsx')
    state.files = [file]; state.file = file
    state.classifications = [{ name: file.name, status: 'classified', confirmed: true, sheets: [], ...(kind === 'receipt' ? { conversion_receipt: { purpose: 'data_template_test_only', print_layout_verified: false, warnings: ['自定义纸张 256 的实际尺寸未验证'] } } : { usage_restrictions: ['打印版式未验证'] }) }]
    state.review = { review_id: 'r1', sheets: [], cells: [], proposal: proposal('v1') }
    state.proposals = [proposal('v1')]; state.name = 'test-only'; state.publishToTenant = true
    api.saveReviewedExcel.mockClear()
    await flushPromises()
    expect(wrapper.text()).toContain('打印版式未验证')
    expect(wrapper.findAll('input[type=checkbox]').find(el => el.element.closest('label')?.textContent?.includes('确认发布'))!.attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('button').find(b => b.text() === '保存所选模板')!.attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('button').find(b => b.text() === '预览清理候选')!.attributes('disabled')).toBeUndefined()
    expect(wrapper.findAll('button').filter(b => b.text() === '下载候选核对').every(b => b.attributes('disabled') === undefined)).toBe(true)
    await (state.save as () => Promise<void>)()
    expect(api.saveReviewedExcel).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('retains top-level restrictions when restoring a saved classification', async () => {
    const receipt = { converter: 'python', source_sha256: 'a'.repeat(64), derived_sha256: '07'.repeat(32), purpose: 'data_template_test_only', print_layout_verified: false, warnings: ['WPS 扩展未验证'] }
    const item = { classification_id: 'saved-limited', name: 'test-only.xlsx', sha256: '07'.repeat(32), conversion_receipt: receipt, usage_restrictions: ['打印版式未验证'], latest: { version: 'v1', confirmed: false, model_status: 'not_called', sheets: [] } }
    api.recentClassifications.mockResolvedValue({ files: [item] })
    vi.stubGlobal('crypto', { randomUUID: () => 'restore-key', subtle: { digest: vi.fn().mockResolvedValue(new Uint8Array(32).fill(7).buffer) } })
    const wrapper = mount(ReviewedExcelTemplate)
    try {
      const file = new File(['source'], 'test-only.xlsx')
      Object.defineProperty(file, 'arrayBuffer', { value: async () => new ArrayBuffer(1) })
      const input = wrapper.find('input[type=file]'); Object.defineProperty(input.element, 'files', { value: [file] })
      await input.trigger('change')
      await wrapper.findAll('button').find(b => b.text() === '查看已保存分类')!.trigger('click'); await flushPromises()
      await wrapper.findAll('button').find(b => b.text() === '恢复此分类并继续')!.trigger('click'); await flushPromises()
      const state = wrapper.vm.$.setupState as Record<string, unknown>
      expect((state.classifications as { conversion_receipt: unknown }[])[0].conversion_receipt).toEqual(receipt)
      expect(state.publicationRestricted).toBe(true)
      expect(wrapper.text()).toContain('WPS 扩展未验证')
    } finally { wrapper.unmount(); vi.unstubAllGlobals() }
  })
  it('does not request conversion consent for an existing legacy classification recovery', async () => {
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(false)
    api.archiveAssets.mockResolvedValue({ assets: [{ id: 'existing', name: 'old.xls', state: 'active', versions: [{ id: 'existing-v', version: 1, status: 'ready', sha256: 'a'.repeat(64), classification_id: 'existing-c' }] }] })
    api.classifyArchiveVersion.mockReset().mockResolvedValue({ name: 'old.xlsx', status: 'classified', classification_id: 'existing-c', version: 'v1', sheets: [] })
    api.downloadClassificationSource.mockResolvedValue({ blob: async () => new Blob(['derived']) })
    const wrapper = mount(ReviewedExcelTemplate)
    try {
      await wrapper.findAll('button').find(b => b.text() === '查看原件档案')!.trigger('click'); await flushPromises()
      await wrapper.findAll('button').find(b => b.text() === '分类此版本')!.trigger('click'); await flushPromises()
      expect(confirmation).not.toHaveBeenCalled()
      expect(api.classifyArchiveVersion).toHaveBeenCalledTimes(1)
      expect(api.classifyArchiveVersion.mock.calls[0][1].has('legacy_test_only')).toBe(false)
      expect(api.downloadClassificationSource).toHaveBeenLastCalledWith('existing-c')
    } finally { wrapper.unmount(); confirmation.mockRestore() }
  })
  it.each([0, 1, 20, 200, 201])('enforces the 200 file limit for %i selections', async (count) => {
    const wrapper = mount(ReviewedExcelTemplate); const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: Array.from({ length: count }, (_, i) => new File(['a'], `${i}.xlsx`)) })
    await input.trigger('change')
    const button = wrapper.findAll('button').find((b) => b.text() === '开始处理')!
    expect(button.attributes('disabled') !== undefined).toBe(count === 0 || count > 200)
    if (count > 200) expect(wrapper.text()).toContain('一次最多上传 200 个文件')
  })
  it('blocks classification when archive admission fails and preserves request identity for retry', async () => {
    api.archiveClassifyExcel.mockReset().mockRejectedValue(new Error('归档配额尚未配置'))
    const wrapper = mount(ReviewedExcelTemplate)
    const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [new File(['a'], 'sample.xlsx')] })
    await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('归档配额尚未配置')
    expect(wrapper.findAll('.classification-region')).toHaveLength(0)
    const first = api.archiveClassifyExcel.mock.calls[0][0] as FormData
    await wrapper.findAll('button').find((b) => b.text() === '重试未完成文件')!.trigger('click'); await flushPromises()
    const second = api.archiveClassifyExcel.mock.calls[1][0] as FormData
    expect(first.get('request_key')).toEqual(second.get('request_key'))
  })
  it('keeps administrator panel only outside chatlike intake', () => {
    expect(mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } }).find('.etl-admin-panel').exists()).toBe(false)
    expect(mount(ReviewedExcelTemplate).find('.etl-admin-panel').exists()).toBe(true)
  })
  it('records composer requirement text on user intake', async () => {
    const wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    await wrapper.get('.etl-composer__input').setValue('保留客户栏，清理空白行')
    await wrapper.get('.etl-composer__send').trigger('click')
    expect(wrapper.text()).toContain('整理要求：保留客户栏，清理空白行')
    wrapper.unmount()
  })
  it('shows administrator quota and a dependency-blocked archive withdrawal', async () => {
    api.archiveQuota.mockResolvedValue({ configured: true, limit_bytes: 1000, reserved_bytes: 300 })
    api.archiveAssets.mockResolvedValue({ assets: [{ id: 'asset-1', name: '报价.xlsx', state: 'active', versions: [{ id: 'v1', version: 1, status: 'ready', sha256: 'abc', classification_id: 'c1' }] }] })
    api.setArchiveAssetState.mockRejectedValue(new Error('归档存在分类依赖或待核对版本，不能撤回'))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(ReviewedExcelTemplate)
    await wrapper.findAll('button').find((b) => b.text() === '查看配额')!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('已预留 300 / 1000 字节')
    await wrapper.findAll('button').find((b) => b.text() === '查看原件档案')!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('版本 1')
    await wrapper.findAll('button').find((b) => b.text() === '撤回')!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('存在分类依赖')
    confirm.mockRestore()
  })
  it('loads the bound derived source after legacy archive classification and previews those same bytes', async () => {
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const sheets = [{ sheet: 'Sheet', labels: ['quotation'], checked_cells: 1, evidence: [], regions: [{ range: 'A1:A1', labels: ['quotation'], header_cells: [], merged_ranges: [], possible_shared_context: [], evidence: [] }] }]
    api.archiveAssets.mockResolvedValue({ assets: [{ id: 'asset-xls', name: 'legacy.xls', state: 'active', versions: [{ id: 'xls-v1', version: 1, status: 'ready', sha256: 'a'.repeat(64), classification_id: null }] }] })
    api.classifyArchiveVersion.mockResolvedValue({ name: 'legacy.xlsx', status: 'classified', classification_id: 'converted-id', version: 'converted-version', sha256: 'derived-hash', sheets, model_status: 'not_called', confirmed: true })
    api.downloadClassificationSource.mockReset().mockResolvedValue({ blob: async () => new Blob(['persistent-derived-bytes']) })
    api.downloadArchiveVersion.mockReset().mockResolvedValue({ blob: async () => new Blob(['original-xls-bytes']) })
    api.reviewExcel.mockReset().mockResolvedValue({ review_id: 'review', sha256: 'derived-hash', sheets: ['Sheet'], cells: [], proposal: proposal('v1') })
    const wrapper = mount(ReviewedExcelTemplate)
    await wrapper.findAll('button').find(b => b.text() === '查看原件档案')!.trigger('click'); await flushPromises()
    await wrapper.findAll('button').find(b => b.text() === '分类此版本')!.trigger('click'); await flushPromises()
    expect(api.downloadClassificationSource).toHaveBeenCalledWith('converted-id')
    expect(api.downloadArchiveVersion).not.toHaveBeenCalled()
    const state = wrapper.vm.$.setupState as Record<string, unknown>
    expect((state.file as File).name).toBe('legacy.xlsx')
    expect((state.file as File).size).toBe(new Blob(['persistent-derived-bytes']).size)
    state.initialModel = false
    await flushPromises()
    await wrapper.findAll('button').find(b => b.text().includes('预览清理'))!.trigger('click'); await flushPromises()
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    const form = api.reviewExcel.mock.calls[0][0] as FormData
    expect((form.get('file') as File).name).toBe('legacy.xlsx')
    expect((form.get('file') as File).size).toBe(new Blob(['persistent-derived-bytes']).size)
    expect(form.get('classification_id')).toBe('converted-id')
    expect(api.classifyArchiveVersion.mock.calls.at(-1)![1].get('legacy_test_only')).toBe('true')
    expect(api.classifyArchiveVersion.mock.calls.at(-1)![1].get('legacy_source_sha256')).toBe('a'.repeat(64))
    confirmation.mockRestore()
  })
  it('only reclassifies after explicit confirmation and clears every old authorization and preview', async () => {
    const sheet = { sheet: '表', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [] }
    api.archiveAssets.mockResolvedValue({ assets: [{ id: 'asset-1', name: '报价.xlsx', state: 'active', versions: [{ id: 'v1', version: 1, status: 'ready', sha256: 'abc', classification_id: 'old' }] }] })
    api.classifyArchiveVersion.mockReset().mockResolvedValue({ name: '报价.xlsx', status: 'classified', classification_id: 'new', version: 'v-new', sheets: [sheet], model_status: 'not_called', confirmed: false })
    api.downloadClassificationSource.mockResolvedValue({ blob: async () => new Blob(['derived-test']) })
    api.analyzeClassification.mockClear(); api.reviewExcel.mockClear()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const wrapper = mount(ReviewedExcelTemplate)
    await wrapper.findAll('button').find((b) => b.text() === '查看原件档案')!.trigger('click'); await flushPromises()
    const button = wrapper.findAll('button').find((b) => b.text() === '重新分类（保留历史）')!
    expect(api.classifyArchiveVersion).not.toHaveBeenCalled()
    await button.trigger('click'); await flushPromises()
    expect(api.classifyArchiveVersion).not.toHaveBeenCalled()
    const state = wrapper.vm.$.setupState as Record<string, unknown>
    for (const key of ['classificationSampleAuthorized', 'classificationOwnFileAuthorized', 'sampleAuthorized', 'templateOwnFileAuthorized', 'initialModel', 'consent', 'publishToTenant']) state[key] = true
    state.retryBudget = { old: true }; state.autoSlices = { old: { version: 'v-old', slices: [] } }
    state.selectedSliceKey = 'old-slice'; state.proposals = [proposal('old-preview')]; state.savedId = 'old-template'
    confirm.mockReturnValue(true)
    await button.trigger('click'); await flushPromises()
    expect(api.classifyArchiveVersion).toHaveBeenCalledTimes(1)
    const [id, form] = api.classifyArchiveVersion.mock.calls[0] as [string, FormData]
    expect(id).toBe('v1'); expect(form.get('reclassify')).toBe('true'); expect(form.get('expected_classification_id')).toBe('old')
    for (const key of ['classificationSampleAuthorized', 'classificationOwnFileAuthorized', 'sampleAuthorized', 'templateOwnFileAuthorized', 'initialModel', 'consent', 'publishToTenant']) expect(state[key]).toBe(false)
    expect(state.retryBudget).toEqual({}); expect(state.autoSlices).toEqual({}); expect(state.proposals).toEqual([]); expect(state.savedId).toBe(''); expect(state.selectedSliceKey).toBe('')
    expect(api.analyzeClassification).not.toHaveBeenCalled(); expect(api.reviewExcel).not.toHaveBeenCalled()
    confirm.mockRestore()
  })
  it('stops before the next model request and resumes without repeating the completed one', async () => {
    const sheet = { sheet: '表', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [] }
    api.classifyExcel.mockResolvedValue({ files: [1, 2].map((n) => ({ name: `${n}.xlsx`, status: 'classified', classification_id: `cancel${n}`, version: 'v1', sheets: [sheet] })) })
    let finish!: (value: unknown) => void
    api.analyzeClassification.mockReset().mockImplementationOnce(() => new Promise((resolve) => { finish = resolve })).mockResolvedValue({ version: 'v2', model_status: 'returned', sheets: [sheet] })
    const wrapper = mount(ReviewedExcelTemplate); const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [1, 2].map((n) => new File(['x'], `${n}.xlsx`)) }); await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    await wrapper.findAll('input[type=checkbox]').find((el) => el.element.closest('label')?.textContent?.includes('所有待分析文件'))!.setValue(true)
    const analyze = wrapper.findAll('button').find((b) => b.text().includes('模型分析已分类'))!
    await analyze.trigger('click'); await wrapper.vm.$nextTick()
    await wrapper.findAll('button').find((b) => b.text().includes('停止后续分析'))!.trigger('click')
    finish({ version: 'v2', model_status: 'returned', sheets: [sheet] }); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('已停止后续批次')
    await analyze.trigger('click'); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(2)
    expect(api.analyzeClassification.mock.calls.at(-1)![0]).toBe('cancel2')
  })
  it('shows platform model authorization copy instead of MiMo/Luna/Terra aliases', async () => {
    const sheet = { sheet: '表', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [] }
    api.classifyExcel.mockResolvedValue({ files: [{ name: '1.xlsx', status: 'classified', classification_id: 'p1', version: 'v1', sheets: [sheet] }] })
    const wrapper = mount(ReviewedExcelTemplate)
    const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], '1.xlsx')] })
    await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('模型调用走软件当前平台默认模型')
    expect(wrapper.text()).toContain('发送至平台模型')
    expect(wrapper.text()).toContain('platform/default-chat')
    expect(wrapper.text()).not.toContain('发送至 MiMo')
    expect(wrapper.text()).toContain('Luna/Terra 私有别名不作为本页默认')
    wrapper.unmount()
  })
  it('authorizes only the selected owner file for platform-model classification', async () => {
    const sheet = { sheet: '表', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [] }
    api.classifyExcel.mockResolvedValue({ files: [1, 2].map((n) => ({ name: `${n}.xlsx`, status: 'classified', classification_id: `own${n}`, version: 'v1', sheets: [sheet] })) })
    api.analyzeClassification.mockReset().mockResolvedValue({ version: 'v2', model_status: 'returned', sheets: [sheet] })
    const wrapper = mount(ReviewedExcelTemplate); const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [1, 2].map((n) => new File(['x'], `${n}.xlsx`)) }); await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    const owner = wrapper.findAll('input[type=checkbox]').find((el) => el.element.closest('label')?.textContent?.includes('仅发送当前文件'))!
    await owner.setValue(true)
    await wrapper.findAll('button').find((b) => b.text().includes('模型分析已分类'))!.trigger('click'); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    expect(api.analyzeClassification.mock.calls[0][0]).toBe('own1')
    const form = api.analyzeClassification.mock.calls[0][1] as FormData
    expect(form.get('own_file_authorized')).toBe('true')
    expect(form.get('sample_authorized')).toBeNull()
  })
  it('stops at a pending batch boundary and resumes the remaining batch', async () => {
    const sheet = { sheet: '表', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [] }
    api.classifyExcel.mockResolvedValue({ files: [{ name: '甲.xlsx', status: 'classified', classification_id: 'batch1', version: 'v1', sheets: [sheet] }] })
    let finish!: (value: unknown) => void
    api.analyzeClassification.mockReset().mockImplementationOnce(() => new Promise((resolve) => { finish = resolve })).mockResolvedValue({ version: 'v2', model_status: 'returned', sheets: [sheet] })
    const wrapper = mount(ReviewedExcelTemplate); const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], '甲.xlsx')] }); await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    await wrapper.findAll('input[type=checkbox]').find((el) => el.element.closest('label')?.textContent?.includes('所有待分析文件'))!.setValue(true)
    const analyze = wrapper.findAll('button').find((b) => b.text().includes('模型分析已分类'))!
    await analyze.trigger('click'); await wrapper.vm.$nextTick()
    await wrapper.findAll('button').find((b) => b.text().includes('停止后续分析'))!.trigger('click')
    finish({ phase: 'pending', version: 'v1', checkpoint: { phase: 'ready', completed: 1, total: 2, max_calls: 2, message: '可继续剩余批次' } }); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('批次 1/2')
    await analyze.trigger('click'); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(2)
  })
  it('requires a fresh user action to continue after the per-round budget', async () => {
    const sheet = { sheet: '表', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [] }
    api.classifyExcel.mockResolvedValue({ files: [{ name: '甲.xlsx', status: 'classified', classification_id: 'pause1', version: 'v1', sheets: [sheet] }] })
    api.analyzeClassification.mockReset().mockResolvedValueOnce({ phase: 'paused', version: 'v1', checkpoint: { phase: 'paused', completed: 1, total: 2, max_calls: 1, message: '本轮预算已用完；确认后可继续剩余批次' } }).mockResolvedValue({ version: 'v2', model_status: 'returned', sheets: [sheet] })
    const wrapper = mount(ReviewedExcelTemplate); const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], '甲.xlsx')] }); await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    await wrapper.findAll('input[type=checkbox]').find((el) => el.element.closest('label')?.textContent?.includes('所有待分析文件'))!.setValue(true)
    const analyze = wrapper.findAll('button').find((b) => b.text().includes('模型分析已分类'))!
    await analyze.trigger('click'); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('本轮预算已用完')
    await analyze.trigger('click'); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(2)
    expect((api.analyzeClassification.mock.calls.at(-1)![1] as FormData).get('continue_authorized')).toBe('true')
  })
  it('isolates model failures and never retries unknown outcomes automatically', async () => {
    const sheet = { sheet: '表', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [] }
    api.classifyExcel.mockResolvedValue({ files: [1, 2, 3].map((n) => ({ name: `${n}.xlsx`, status: 'classified', classification_id: `id${n}`, version: 'v1', sheets: [sheet] })) })
    api.analyzeClassification.mockReset().mockRejectedValueOnce(new Error('服务暂不可用')).mockResolvedValue({ version: 'v2', model_status: 'returned', sheets: [sheet] })
    const wrapper = mount(ReviewedExcelTemplate); const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [1, 2, 3].map((n) => new File(['x'], `${n}.xlsx`)) }); await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    await wrapper.findAll('input[type=checkbox]').find((el) => el.element.closest('label')?.textContent?.includes('所有待分析文件'))!.setValue(true)
    const analyze = wrapper.findAll('button').find((b) => b.text().includes('模型分析已分类'))!
    await analyze.trigger('click'); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(3)
    expect(wrapper.text()).toContain('服务暂不可用')
    await analyze.trigger('click'); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(3)
    expect(wrapper.text()).toContain('请求结果可能未知')
    expect(wrapper.text()).toContain('结果未知，不可重发；需人工核对')
    expect(wrapper.text()).not.toContain('核对历史后可重试')
  })
  it('shows the original model suggestion and repeated-header conflict', async () => {
    const region = { range: 'A22:F40', labels: ['unknown'], suggested_labels: ['purchase'], context_warning: '相邻区域出现重复表头且模型分类不同，可能是续表，需人工确认。', checked_cells: 3, evidence: [], parent_heading: '', dependency_status: '待确认', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [] }
    api.classifyExcel.mockResolvedValue({ files: [{ name: '合成.xlsx', status: 'classified', classification_id: 'neutral', version: 'v1', sheets: [{ sheet: '表', labels: ['unknown'], checked_cells: 3, evidence: [], regions: [region] }] }] })
    const wrapper = mount(ReviewedExcelTemplate); const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], '合成.xlsx')] }); await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('模型原建议 采购；')
    expect(wrapper.text()).toContain('相邻区域出现重复表头且模型分类不同，可能是续表，需人工确认。')
  })
  it('shows fragment relationships as unconfirmed and does not merge matching labels', async () => {
    const region = (range: string) => ({ range, value_extent: 'B3:D4', labels: ['quotation'], checked_cells: 2, evidence: [], parent_heading: '', dependency_status: '待确认', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [] })
    api.classifyExcel.mockResolvedValue({ files: [{ name: '合成.xlsx', status: 'classified', classification_id: 'fragment', version: 'v1', fragment_links: { items: [{ sheet: '报价', first: 'A3:F21', second: 'A22:F40', shared_dependencies: [{ sheet: '报价', cell: 'A1' }], repeated_header_observed: false, status: 'candidate' }], omitted: 0 }, sheets: [{ sheet: '报价', labels: ['quotation'], checked_cells: 2, evidence: [], regions: [region('A3:F21'), region('A22:F40')] }] }] })
    const wrapper = mount(ReviewedExcelTemplate); const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], '合成.xlsx')] }); await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('同类别不会自动合并')
    expect(wrapper.text()).toContain('不表示已精确裁剪')
    expect(wrapper.text()).toContain('非空格范围 B3:D4')
    expect(wrapper.text()).toContain('A3:F21 ↔ A22:F40')
    expect(wrapper.text()).toContain('模型共同引用 报价!A1')
    expect(wrapper.text()).toContain('关联仍待确认')
    expect(wrapper.findAll('.classification-region')).toHaveLength(2)
    await wrapper.find('.classification-region details input').setValue('A3:F20')
    expect(wrapper.text()).toContain('之前的关联候选不再适用')
  })

  it('warns when candidate fragments have conflicting document identities', async () => {
    const region = (range: string) => ({ range, labels: ['quotation'], checked_cells: 2, evidence: [], parent_heading: '', dependency_status: '待确认', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [] })
    api.classifyExcel.mockResolvedValue({ files: [{ name: '合成.xlsx', status: 'classified', classification_id: 'fragment-conflict', version: 'v1', fragment_links: { items: [{ sheet: '报价', first: 'A1:B5', second: 'A6:B10', shared_dependencies: [], repeated_header_observed: true, status: 'identity_conflict' }], omitted: 0 }, sheets: [{ sheet: '报价', labels: ['quotation'], checked_cells: 2, evidence: [], regions: [region('A1:B5'), region('A6:B10')] }] }] })
    const wrapper = mount(ReviewedExcelTemplate); const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], '合成.xlsx')] }); await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('单据身份信息不一致，不能按续表合并')
  })
  it('shows read-only print-area limitations during classification', async () => {
    api.classifyExcel.mockResolvedValue({ files: [{ name: '报价.xlsx', status: 'classified', classification_id: 'print', version: 'v1', read_only_print_areas: [{ sheet: '报价', value: '报价!$1:$19' }], sheets: [] }] })
    const wrapper = mount(ReviewedExcelTemplate); const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], '报价.xlsx')] }); await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('逐文档提取时可能需要确认派生打印区域')
    expect(wrapper.text()).toContain('报价!$1:$19')
  })
  it('shows when a template write is in progress or its outcome needs reconciliation', async () => {
    api.recentClassifications.mockResolvedValue({ files: [{ classification_id: 'locked', name: '合成.xlsx', sha256: 'hash', template_write_state: 'locked', latest: null }] })
    const wrapper = mount(ReviewedExcelTemplate)
    await wrapper.findAll('button').find((button) => button.text().includes('查看已保存分类'))!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('模板保存正在进行或结果待核对；请勿重复保存')
  })
  it('sends selected links for confirmation and displays the resulting document', async () => {
    const region = (range: string) => ({ range, labels: ['quotation'], checked_cells: 2, evidence: [], parent_heading: '', dependency_status: '待确认', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [] })
    const sheets = [{ sheet: '报价', labels: ['quotation'], checked_cells: 2, evidence: [], regions: [region('A1:B5'), region('A6:B10')] }]
    const fragment_links = { items: [{ sheet: '报价', first: 'A1:B5', second: 'A6:B10', shared_dependencies: [], repeated_header_observed: true, status: 'candidate' }], omitted: 0 }
    api.classifyExcel.mockResolvedValue({ files: [{ name: '合成.xlsx', status: 'classified', classification_id: 'group', version: 'v1', fragment_links, sheets }] })
    api.confirmClassification.mockResolvedValueOnce({ version: 'v2', confirmed: true, sheets, fragment_links, logical_documents: [{ logical_document_id: 'g', status: 'user_confirmed', fragments: [{ sheet: '报价', range: 'A1:B5' }, { sheet: '报价', range: 'A6:B10' }] }] })
    const wrapper = mount(ReviewedExcelTemplate); const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], '合成.xlsx')] }); await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    await wrapper.findAll('input[type=checkbox]').find((el) => el.element.closest('label')?.textContent?.includes('同一文档'))!.setValue(true)
    await wrapper.findAll('button').find((b) => b.text().includes('确认分类并继续'))!.trigger('click'); await flushPromises()
    const form = api.confirmClassification.mock.calls.at(-1)![1] as FormData
    expect(JSON.parse(String(form.get('links_json')))).toEqual([{ sheet: '报价', first: 'A1:B5', second: 'A6:B10' }])
    expect(wrapper.text()).toContain('已确认同一文档：报价!A1:B5、报价!A6:B10')
    expect(wrapper.text()).toContain('从所选文档片段生成副本')
  })
  it('allows a confirmed file to continue when another file confirmation fails', async () => {
    const region = { range: 'A1:A1', labels: ['unknown'], checked_cells: 1, evidence: [], parent_heading: '', dependency_status: '未分析', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [] }
    const sheet = { sheet: '表', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [region] }
    api.classifyExcel.mockResolvedValue({ files: [
      { name: '甲.xlsx', status: 'classified', classification_id: 'partial-1', version: 'v1', sheets: [sheet] },
      { name: '乙.xlsx', status: 'classified', classification_id: 'partial-2', version: 'v1', sheets: [sheet] },
    ] })
    api.confirmClassification.mockReset().mockResolvedValueOnce({ version: 'v2', confirmed: true, sheets: [sheet] }).mockRejectedValueOnce(new Error('第二个文件版本过期'))
    const wrapper = mount(ReviewedExcelTemplate); const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [new File(['a'], '甲.xlsx'), new File(['b'], '乙.xlsx')] }); await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    await wrapper.findAll('button').find((b) => b.text().includes('确认分类并继续'))!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('第二个文件版本过期')
    expect(wrapper.findAll('button').find((b) => b.text().includes('预览清理'))!.attributes('disabled')).toBeUndefined()
    await wrapper.findAll('input[name="template-file"]')[1].setValue()
    expect(wrapper.findAll('button').find((b) => b.text().includes('预览清理'))!.attributes('disabled')).toBeDefined()
  })
  it('runs explicitly authorized semantic analysis and persists confirmed labels', async () => {
    const region = { range: 'A1:B2', labels: ['unknown'], checked_cells: 1, evidence: [], parent_heading: '', dependency_status: '未分析', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [] }
    const sheet = { sheet: '报价', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [region] }
    api.classifyExcel.mockResolvedValue({ files: [{ name: '报价.xlsx', status: 'classified', classification_id: 'class-semantic', version: 'v1', sheets: [sheet] }] })
    api.analyzeClassification.mockResolvedValue({ version: 'v2', sheets: [{ ...sheet, regions: [{ ...region, labels: ['quotation'] }] }], model_status: 'returned', input_summaries: [{ input_sha256: 'synthetic-digest' }], coverage: [{ sheet: '报价', total: 2, sent: 1, unread: ['B2'], unassigned: ['B2'], value_truncated: [] }] })
    api.recentClassifications.mockResolvedValue({ files: [{ classification_id: 'class-semantic', name: '报价.xlsx', sha256: 'abc', latest: { version: 'v3', confirmed: true, model_status: 'returned', sheets: [{ ...sheet, regions: [{ ...region, labels: ['quotation'] }] }] } }] })
    const wrapper = mount(ReviewedExcelTemplate); const input = wrapper.find('input[type=file]'); Object.defineProperty(input.element, 'files', { value: [new File(['x'], '报价.xlsx')] }); await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    const analyze = wrapper.findAll('button').find((b) => b.text().includes('模型分析已分类'))!
    expect(analyze.attributes('disabled')).toBeDefined()
    await wrapper.findAll('input[type=checkbox]').find((el) => el.element.closest('label')?.textContent?.includes('所有待分析文件'))!.setValue(true)
    await analyze.trigger('click'); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledWith('class-semantic', expect.any(FormData))
    expect(wrapper.text()).toContain('未发送 1 格，未归入区域 1 格')
    expect(wrapper.text()).toContain('查看模型输入摘要及来源坐标（不含正文）')
    expect(wrapper.text()).not.toContain('bounded sample')
    expect(wrapper.text()).toContain('不能视为全文件分类完成')
    await wrapper.find('.classification-region details summary').trigger('click')
    await wrapper.find('.classification-region details input').setValue('A1:A2')
    await wrapper.findAll('button').find((b) => b.text().includes('确认分类并继续'))!.trigger('click'); await flushPromises()
    expect(api.confirmClassification).toHaveBeenCalledWith('class-semantic', expect.any(FormData))
    const confirmation = api.confirmClassification.mock.calls.at(-1)![1] as FormData
    expect(JSON.parse(String(confirmation.get('labels_json')))[0]).toMatchObject({ original_range: 'A1:B2', range: 'A1:A2' })
    await wrapper.findAll('button').find((b) => b.text().includes('查看已保存分类'))!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('A1:B2 报价')
  })
  it('groups multiple files and batch corrects selected regions without requiring a category', async () => {
    const region = (range: string) => ({ range, labels: ['unknown'], checked_cells: 1, evidence: [], parent_heading: '', dependency_status: '未分析', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [] })
    api.classifyExcel.mockResolvedValue({ files: [
      { name: '甲.xlsx', status: 'classified', classification_id: 'class-1', version: 'v1', sheets: [{ sheet: '综合', labels: ['unknown'], checked_cells: 2, evidence: [], regions: [region('A1:B5'), region('A6:B10')] }] },
      { name: '乙.xlsx', status: 'classified', classification_id: 'class-2', version: 'v1', sheets: [{ sheet: '其他', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [region('A1:B2')] }] },
    ] })
    const wrapper = mount(ReviewedExcelTemplate); const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [new File(['a'], '甲.xlsx'), new File(['b'], '乙.xlsx')] }); await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    const rows = wrapper.findAll('.classification-region'); expect(rows).toHaveLength(3)
    await rows[0].find('input[type=checkbox]').setValue(true); await rows[2].find('input[type=checkbox]').setValue(true)
    await wrapper.find('.classification-results select').setValue('quotation')
    await wrapper.findAll('button').find((b) => b.text().includes('应用到选中区域'))!.trigger('click')
    expect(wrapper.text()).toContain('报价：甲.xlsx / 综合 / A1:B5；乙.xlsx / 其他 / A1:B2')
    expect(wrapper.text()).toContain('未知/待理解：甲.xlsx / 综合 / A6:B10')
    await wrapper.findAll('button').find((b) => b.text().includes('确认分类并继续'))!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('未知/待理解，用户已确认继续')
    expect(wrapper.findAll('button').find((b) => b.text().includes('预览清理'))!.attributes('disabled')).toBeUndefined()
    const authorization = wrapper.findAll('input[type=checkbox]').find((el) => el.element.closest('label')?.textContent?.includes('确认此文件'))!
    await authorization.setValue(true)
    await wrapper.findAll('input[name="template-file"]')[1].setValue()
    expect((authorization.element as HTMLInputElement).checked).toBe(false)
  })
  const sliceResults = [0, 1].map(index => ({ index, filename: `${index ? '乙' : '甲'}单.xlsx`, sha256: `slice-${index}`, basis: 'model_group', confirmed: false, fragments: [{ sheet: '报价', range: 'A1:B2' }] }))
  const sliceReview = (id: string) => ({ review_id: id, sha256: 'source', sheets: ['报价'], cells: [], layout: layout(id), proposal: proposal(id), selected_region: { selection_basis: 'model_group' } })
  async function classifiedSlices(checkpoint?: { phase: string; calls_in_round: number; max_calls: number; version?: string; source_sha256?: string }) {
    const sheets = [{ sheet: '报价', labels: ['quotation'], checked_cells: 1, evidence: [], regions: [] }]
    api.classifyExcel.mockResolvedValue({ files: [{ name: '报价.xlsx', status: 'classified', classification_id: 'slices', sha256: 'source-hash', version: 'v1', sheets }] })
    api.analyzeClassification.mockReset().mockResolvedValue({ version: 'v2', model_status: 'returned', sheets })
    api.recentClassifications.mockReset()
    if (checkpoint) {
      api.analyzeClassification.mockRejectedValueOnce(new Error('模型响应验证失败'))
      api.recentClassifications.mockResolvedValue({ files: [{ classification_id: 'slices', sha256: checkpoint.source_sha256 || 'source-hash', latest: { version: 'v1' }, checkpoint: { version: 'v1', completed: 0, total: 2, message: '已核对状态', ...checkpoint } }] })
    }
    api.autoSlices.mockReset().mockResolvedValue({ slices: sliceResults })
    api.reviewExcel.mockReset().mockResolvedValue(sliceReview('甲'))
    api.saveReviewedExcel.mockReset().mockResolvedValue({ template_id: 'saved' })
    const wrapper = mount(ReviewedExcelTemplate)
    const input = wrapper.find('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], '报价.xlsx')] })
    await input.trigger('change')
    await wrapper.findAll('button').find(b => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    await wrapper.findAll('input[type=checkbox]').find(el => el.element.closest('label')?.textContent?.includes('所有待分析文件'))!.setValue(true)
    await wrapper.findAll('button').find(b => b.text().includes('模型分析已分类'))!.trigger('click'); await flushPromises()
    return wrapper
  }
  it.each([0, 1])('retries a persisted failed response only with explicit consent and budget (used=%s)', async used => {
    const wrapper = await classifiedSlices({ phase: 'failed', calls_in_round: used, max_calls: 1 })
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    await wrapper.findAll('button').find(b => b.text() === '模型分析已分类文件')!.trigger('click'); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    const retry = wrapper.findAll('button').find(b => b.text().includes('确认再次调用模型重试'))!
    if (used) {
      expect(retry.attributes('disabled')).toBeDefined()
      await wrapper.findAll('input[type=checkbox]').find(el => el.element.closest('label')?.textContent?.includes('确认开启新一轮预算'))!.setValue(true)
    }
    api.analyzeClassification.mockResolvedValueOnce({ phase: 'pending', version: 'v1', checkpoint: { phase: 'ready', version: 'v1', completed: 1, total: 2, max_calls: 1, calls_in_round: 1, message: '下一批待处理' } })
    await retry.trigger('click'); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(2)
    const form = api.analyzeClassification.mock.calls[1][1] as FormData
    expect(form.get('retry_authorized')).toBe('true')
    expect(form.get('continue_authorized')).toBe(used ? 'true' : null)
    expect(wrapper.findAll('button').some(b => b.text().includes('确认再次调用模型重试'))).toBe(false)
    wrapper.unmount()
  })
  it.each(['inflight', 'stale-failed', 'hash-mismatch', 'ready'])('uses persisted matching checkpoint evidence and preserves %s behavior', async phase => {
    const wrapper = await classifiedSlices({ phase: ['stale-failed', 'hash-mismatch'].includes(phase) ? 'failed' : phase, version: phase === 'stale-failed' ? 'old-version' : 'v1', source_sha256: phase === 'hash-mismatch' ? 'wrong-source' : 'source-hash', calls_in_round: 0, max_calls: 1 })
    expect(wrapper.findAll('button').some(b => b.text().includes('确认再次调用模型重试'))).toBe(false)
    await wrapper.findAll('button').find(b => b.text() === '模型分析已分类文件')!.trigger('click'); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(phase === 'ready' ? 2 : 1)
    if (phase === 'ready') expect((api.analyzeClassification.mock.calls[1][1] as FormData).get('retry_authorized')).toBeNull()
    wrapper.unmount()
  })
  it.each([true, false])('clears prior slice review and sharing consent when next preview fails=%s', async fails => {
    const wrapper = await classifiedSlices()
    const buttons = () => wrapper.findAll('button').filter(b => b.text() === '用此单据生成模板')
    await buttons()[0].trigger('click'); await flushPromises()
    await wrapper.findAll('input[type=checkbox]').find(el => el.element.closest('label')?.textContent?.includes('确认发布'))!.setValue(true)
    const oldSave = wrapper.findAll('button').find(b => b.text() === '保存所选模板')!
    let finish!: () => void
    api.reviewExcel.mockImplementationOnce(() => new Promise((resolve, reject) => { finish = () => fails ? reject(new Error('乙预览失败')) : resolve(sliceReview('乙')) }))
    const second = buttons()[1]
    second.element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    second.element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(api.reviewExcel).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('.reviewed-template__preview')).toHaveLength(0)
    oldSave.element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(api.saveReviewedExcel).not.toHaveBeenCalled()
    finish(); await flushPromises()
    if (fails) {
      expect(wrapper.text()).toContain('乙预览失败')
      expect(wrapper.findAll('button').some(b => b.text() === '保存所选模板')).toBe(false)
    } else {
      const save = wrapper.findAll('button').find(b => b.text() === '保存所选模板')!
      expect(save.attributes('disabled')).toBeDefined()
      await wrapper.findAll('input[type=checkbox]').find(el => el.element.closest('label')?.textContent?.includes('确认发布'))!.setValue(true)
      await save.trigger('click'); await flushPromises()
      const form = api.saveReviewedExcel.mock.calls[0][0] as FormData
      expect(form.get('name')).toBe('乙单'); expect(form.get('review_id')).toBe('乙')
    }
    wrapper.unmount()
  })
  it('reloads slices after a transient failure without reanalyzing or duplicate requests', async () => {
    const wrapper = await classifiedSlices()
    api.autoSlices.mockRejectedValueOnce(new Error('网络中断'))
    const reload = () => wrapper.findAll('button').find(b => b.text().includes('重新加载切片'))!
    await reload().trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('裁切失败：网络中断')
    expect(wrapper.findAll('button').filter(b => b.text() === '用此单据生成模板')).toHaveLength(0)
    let finish!: (value: unknown) => void
    api.autoSlices.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    reload().element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    reload().element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(api.autoSlices).toHaveBeenCalledTimes(3)
    finish({ slices: sliceResults }); await flushPromises()
    expect(wrapper.text()).not.toContain('裁切失败：网络中断')
    expect(wrapper.findAll('button').filter(b => b.text() === '用此单据生成模板')).toHaveLength(2)
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
  it('binds model opt-in to the selected slice and requires fresh authorization for another slice', async () => {
    const wrapper = await classifiedSlices()
    const slices = () => wrapper.findAll('button').filter(b => b.text() === '用此单据生成模板')
    const checkbox = (label: string) => wrapper.findAll('input[type=checkbox]').find(el => el.element.closest('label')?.textContent?.includes(label))!
    await slices()[0].trigger('click'); await flushPromises()
    await checkbox('首轮使用模型').setValue(true)
    await checkbox('的所选文档发送至平台模型').setValue(true)
    await slices()[0].trigger('click'); await flushPromises()
    let form = api.reviewExcel.mock.calls.at(-1)![0] as FormData
    expect(form.get('model_opt_in')).toBe('true'); expect(form.get('own_file_authorized')).toBe('true')
    await slices()[1].trigger('click'); await flushPromises()
    form = api.reviewExcel.mock.calls.at(-1)![0] as FormData
    expect(form.get('model_opt_in')).toBe('false')
    expect(form.get('own_file_authorized')).toBe('false'); expect(form.get('sample_authorized')).toBe('false')
    expect((checkbox('首轮使用模型').element as HTMLInputElement).checked).toBe(false)
    await checkbox('首轮使用模型').setValue(true)
    await checkbox('的所选文档发送至平台模型').setValue(true)
    await slices()[1].trigger('click'); await flushPromises()
    form = api.reviewExcel.mock.calls.at(-1)![0] as FormData
    expect(form.get('auto_slice_index')).toBe('1')
    expect(form.get('model_opt_in')).toBe('true'); expect(form.get('own_file_authorized')).toBe('true')
    wrapper.unmount()
  })
  it('does not reuse budget consent when restoring the same classification at a new version', async () => {
    const wrapper = await classifiedSlices({ phase: 'failed', calls_in_round: 1, max_calls: 1 })
    const budget = () => wrapper.findAll('input[type=checkbox]').find(el => el.element.closest('label')?.textContent?.includes('确认开启新一轮预算'))!
    await budget().setValue(true)
    api.recentClassifications.mockResolvedValue({ files: [{ classification_id: 'slices', name: '报价.xlsx', sha256: '01', latest: { version: 'new-version', confirmed: false, model_status: 'not_called', sheets: [] }, checkpoint: { phase: 'failed', version: 'new-version', completed: 0, total: 2, max_calls: 1, calls_in_round: 1, message: '失败待确认' } }] })
    vi.stubGlobal('crypto', { randomUUID: () => 'test-uuid', subtle: { digest: vi.fn().mockResolvedValue(new Uint8Array([1]).buffer) } })
    try {
      const input = wrapper.find('input[type=file]')
      const file = (input.element as HTMLInputElement).files![0]
      Object.defineProperty(file, 'arrayBuffer', { value: async () => new Uint8Array([1]).buffer })
      await wrapper.findAll('button').find(b => b.text() === '查看已保存分类')!.trigger('click'); await flushPromises()
      await wrapper.findAll('button').find(b => b.text() === '恢复此分类并继续')!.trigger('click'); await flushPromises()
      expect((budget().element as HTMLInputElement).checked).toBe(false)
      const retry = wrapper.findAll('button').find(b => b.text().includes('确认再次调用模型重试'))!
      expect(retry.attributes('disabled')).toBeDefined()
      expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
      await budget().setValue(true)
      await retry.trigger('click'); await flushPromises()
      expect(api.analyzeClassification).toHaveBeenCalledTimes(2)
      const form = api.analyzeClassification.mock.calls[1][1] as FormData
      expect(form.get('version')).toBe('new-version')
      expect(form.get('continue_authorized')).toBe('true')
    } finally { wrapper.unmount(); vi.unstubAllGlobals() }
  })
  it.each([true, false])('restores automatic slices without another model call, load fails=%s', async fails => {
    api.analyzeClassification.mockReset(); api.autoSlices.mockReset()
    if (fails) api.autoSlices.mockRejectedValue(new Error('分类版本已改变'))
    else api.autoSlices.mockResolvedValue({ slices: sliceResults })
    api.recentClassifications.mockResolvedValue({ files: [{ classification_id: 'restored', name: '恢复.xlsx', sha256: '01', latest: { version: 'current-version', confirmed: false, model_status: 'returned', sheets: [] } }] })
    vi.stubGlobal('crypto', { randomUUID: () => 'test-uuid', subtle: { digest: vi.fn().mockResolvedValue(new Uint8Array([1]).buffer) } })
    const wrapper = mount(ReviewedExcelTemplate)
    try {
      const file = new File(['x'], '恢复.xlsx')
      Object.defineProperty(file, 'arrayBuffer', { value: async () => new Uint8Array([1]).buffer })
      const input = wrapper.find('input[type=file]'); Object.defineProperty(input.element, 'files', { value: [file] })
      await input.trigger('change')
      await wrapper.findAll('button').find(b => b.text().includes('查看已保存分类'))!.trigger('click'); await flushPromises()
      await wrapper.findAll('button').find(b => b.text() === '恢复此分类并继续')!.trigger('click'); await flushPromises()
      expect(api.autoSlices).toHaveBeenCalledWith('restored', 'current-version')
      expect(api.analyzeClassification).not.toHaveBeenCalled()
      expect(wrapper.findAll('button').filter(b => b.text() === '用此单据生成模板')).toHaveLength(fails ? 0 : 2)
      if (fails) expect(wrapper.text()).toContain('裁切失败：分类版本已改变')
    } finally { wrapper.unmount(); vi.unstubAllGlobals() }
  })
  it('displays generated results and saves the chosen plan without cell selection', async () => {
    api.classifyExcel.mockResolvedValue({ files: [{ name: '报价.xlsx', status: 'classified', classification_id: 'class-1', version: 'v1', sheets: [{ sheet: '报价', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [{ range: 'A1:B2', labels: ['unknown'], checked_cells: 1, evidence: [], parent_heading: '', dependency_status: '未分析', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [] }] }] }] })
    api.reviewExcel.mockResolvedValue({ review_id: 'r1', sha256: 'source', sheets: ['报价'], cells: [], layout: layout('客户甲'), proposal: proposal('v1'), selected_region: { print_area_mode: 'selected', source_print_areas: [{ sheet: '报价', value: '报价!$1:$19' }], derived_print_area: "'报价'!$A$25" } })
    api.saveReviewedExcel.mockResolvedValue({ template_id: 'db:1' })
    const wrapper = mount(ReviewedExcelTemplate)
    const input = wrapper.find('input[type=file]'); Object.defineProperty(input.element, 'files', { value: [new File(['x'], '报价.xlsx')] }); await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('待确认；仍可预览模板')
    await wrapper.find('.classification-region input[type=checkbox]').setValue(true)
    await wrapper.find('.classification-results select').setValue('quotation')
    await wrapper.findAll('button').find((b) => b.text().includes('应用到选中'))!.trigger('click')
    expect((wrapper.findAll('.classification-region input[type=checkbox]')[1].element as HTMLInputElement).checked).toBe(true)
    await wrapper.findAll('button').find((b) => b.text().includes('确认分类并继续'))!.trigger('click'); await flushPromises()
    await wrapper.findAll('input[type=checkbox]').find((el) => el.element.closest('label')?.textContent?.includes('派生文件中将打印范围设为所选片段'))!.setValue(true)
    await wrapper.findAll('button').find((b) => b.text().includes('预览清理'))!.trigger('click'); await flushPromises()
    expect((api.reviewExcel.mock.calls.at(-1)![0] as FormData).get('print_area_mode')).toBe('selected')
    expect(wrapper.text()).toContain('原范围 报价!$1:$19 → 派生范围')
    const cards = wrapper.findAll('.reviewed-template__preview')
    expect(cards).toHaveLength(4); expect(cards[0].text()).toContain('客户甲'); expect(cards[2].find('td').text()).toBe('')
    expect(cards[3].text()).toContain('与模板 2 清理结果相同')
    expect(wrapper.find('.reviewed-template__cells').exists()).toBe(false)
    await wrapper.findAll('.reviewed-template__preview--a4')[1].trigger('click')
    await wrapper.findAll('input[type=checkbox]').find((el) => el.element.closest('label')?.textContent?.includes('确认发布'))!.setValue(true)
    await wrapper.findAll('button').find((b) => b.text().includes('保存所选模板'))!.trigger('click'); await flushPromises()
    const form = api.saveReviewedExcel.mock.calls.at(-1)![0] as FormData
    expect(form.get('candidate_id')).toBe('table'); expect(JSON.parse(String(form.get('selections')))).toEqual([{ sheet: '报价', cell: 'B2' }]); expect(wrapper.emitted('saved')).toHaveLength(1)
  })
  it('keeps the previous three results when feedback fails and shows a new set on success', async () => {
    api.classifyExcel.mockResolvedValue({ files: [{ name: '报价.xlsx', status: 'classified', classification_id: 'class-1', version: 'v1', sheets: [{ sheet: '报价', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [{ range: 'A1:B2', labels: ['unknown'], checked_cells: 1, evidence: [], parent_heading: '', dependency_status: '未分析', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [] }] }] }] })
    const first = proposal('a'.repeat(64)); const second = { ...proposal('b'.repeat(64)), parent_version: first.version, model: { status: 'returned' } }
    api.reviewExcel.mockResolvedValue({ review_id: 'r2', sha256: 'source', sheets: ['报价'], cells: [], layout: layout('客户甲'), proposal: first })
    api.refineReviewedExcel.mockRejectedValueOnce(new Error('模型不可用')).mockResolvedValueOnce({ proposal: second })
    const wrapper = mount(ReviewedExcelTemplate); const input = wrapper.find('input[type=file]'); Object.defineProperty(input.element, 'files', { value: [new File(['x'], '报价.xlsx')] }); await input.trigger('change')
    await wrapper.findAll('button').find((b) => b.text() === '开始处理')!.trigger('click'); await flushPromises()
    await wrapper.findAll('button').find((b) => b.text().includes('确认分类并继续'))!.trigger('click'); await flushPromises()
    await wrapper.findAll('button').find((b) => b.text().includes('预览清理'))!.trigger('click'); await flushPromises()
    await wrapper.find('input[placeholder]').setValue('保留备注')
    await wrapper.findAll('input[type=checkbox]').find((el) => el.element.closest('label')?.textContent?.includes('确认此文件'))!.setValue(true)
    await wrapper.findAll('input[type=checkbox]').find((el) => el.element.closest('label')?.textContent?.includes('同意向'))!.setValue(true)
    const next = wrapper.findAll('button').find((b) => b.text().includes('生成新一轮'))!; await next.trigger('click'); await flushPromises(); expect(wrapper.text()).toContain('模型不可用'); expect(wrapper.findAll('.reviewed-template__preview')).toHaveLength(4)
    await next.trigger('click'); await flushPromises(); expect(wrapper.text()).toContain('模型已返回建议'); expect(wrapper.findAll('.reviewed-template__preview')).toHaveLength(4)
    await wrapper.findAll('button').find((b) => b.text().includes('查看版本 1'))!.trigger('click'); expect(wrapper.text()).toContain('确定性规则建议')
  })

  it('composer drag-drop stages files without archiving until start', async () => {
    api.archiveClassifyExcel.mockResolvedValue({ name: 'drag.xlsx', status: 'classified', classification_id: 'd1', version: 'v1', sheets: [{ sheet: 'S', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [{ range: 'A1:B2', labels: ['unknown'], checked_cells: 1, parent_heading: '', dependency_status: '待确认', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [], evidence: [] }] }] })
    const wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    try {
      const composer = wrapper.get('.etl-composer')
      const file = new File(['x'], 'drag.xlsx')
      await composer.trigger('dragenter', { dataTransfer: { files: [file] } })
      expect(wrapper.find('.etl-composer--dragover').exists()).toBe(true)
      await composer.trigger('dragleave', { relatedTarget: null })
      await composer.trigger('drop', { dataTransfer: { files: [file] } })
      await flushPromises()
      expect(api.archiveClassifyExcel).not.toHaveBeenCalled()
      expect(wrapper.text()).toContain('drag.xlsx')
      await wrapper.get('.etl-composer__start').trigger('click'); await flushPromises()
      expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(1)
      expect(wrapper.find('.etl-intake-empty').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })

  it('opens the hidden file picker from the attach control', async () => {
    const wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    try {
      const input = wrapper.get('input.etl-composer__file-input').element as HTMLInputElement
      const click = vi.spyOn(input, 'click').mockImplementation(() => undefined)
      await wrapper.get('.etl-composer__attach').trigger('click')
      expect(click).toHaveBeenCalledTimes(1)
    } finally { wrapper.unmount() }
  })

  it('marks composer drag-over on dragover and clears on leave', async () => {
    const wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    try {
      const composer = wrapper.get('.etl-composer')
      await composer.trigger('dragover', { dataTransfer: { files: [] } })
      expect(wrapper.find('.etl-composer--dragover').exists()).toBe(true)
      await composer.trigger('dragleave', { relatedTarget: null })
      expect(wrapper.find('.etl-composer--dragover').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })

  it('polls auto-ingest progress until terminal and surfaces poll errors', async () => {
    vi.useFakeTimers()
    etl.autoIngestProgress
      .mockResolvedValueOnce({ status: 'running', kb_progress: { pct: 40, stage: 'write', message: '写入中' }, business_progress: { pct: 10, stage: 'queued', message: '排队' } })
      .mockResolvedValueOnce({ status: 'applied', kb_progress: { pct: 100, stage: 'done', message: '完成' }, business_progress: { pct: 100, stage: 'done', message: '完成' } })
      .mockRejectedValueOnce(new Error('进度读取失败'))
    const wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    try {
      const state = wrapper.vm.$.setupState as Record<string, unknown>
      state.savedId = 'tpl-ingest'
      ;(state.startIngestPoll as (id: string) => void)('batch-1')
      await flushPromises()
      expect(etl.autoIngestProgress).toHaveBeenCalledWith('batch-1')
      expect(wrapper.find('[aria-label="自动入库真实进度"]').exists()).toBe(true)
      expect(wrapper.text()).toContain('写入中')
      await vi.advanceTimersByTimeAsync(800)
      await flushPromises()
      expect(wrapper.text()).toContain('自动入库批次 batch-1')
      ;(state.startIngestPoll as (id: string) => void)('batch-err')
      await flushPromises()
      expect(wrapper.text()).toContain('进度读取失败')
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })



  it('on archiveOnSelect, picking an A4 capsule saves with private_intake and starts ingest poll', async () => {
    api.saveReviewedExcel.mockResolvedValue({
      template_id: 'db:42',
      auto_ingest: { batch_id: 'batch-pick', status: 'running', kb_progress: { pct: 5, stage: 'queued', message: '排队' }, business_progress: { pct: 0, stage: 'queued', message: '排队' } },
    })
    etl.autoIngestProgress.mockResolvedValue({ status: 'running', kb_progress: { pct: 5 }, business_progress: { pct: 0 } })
    const wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    try {
      const file = new File(['x'], 'pick.xlsx')
      const input = wrapper.find('input[type=file]')
      Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
      await input.trigger('change'); await flushPromises()
      const state = wrapper.vm.$.setupState as Record<string, unknown>
      state.classifications = [{ name: file.name, status: 'classified', confirmed: true, sheets: [] }]
      state.file = file
      state.name = 'pick-tpl'
      state.review = { review_id: 'r-pick', sheets: [], cells: [], proposal: proposal('v1'), selected_region: { selection_basis: 'model_group' } }
      state.proposals = [proposal('v1')]
      state.templatePickerOpen = true
      await flushPromises()
      expect(wrapper.text()).toContain('点选绿胶囊即选用并开始自动入库')
      expect(wrapper.findAll('button').some(b => b.text() === '保存所选模板')).toBe(false)
      expect(wrapper.findAll('button').some(b => b.text() === '使用此模板并入库')).toBe(true)
      expect(wrapper.findAll('input[type=checkbox]').some(el => el.element.closest('label')?.textContent?.includes('确认发布'))).toBe(false)
      await wrapper.findAll('.reviewed-template__preview--a4')[1].trigger('click')
      await flushPromises()
      expect(api.saveReviewedExcel).toHaveBeenCalledTimes(1)
      const form = api.saveReviewedExcel.mock.calls[0][0] as FormData
      expect(form.get('private_intake')).toBe('true')
      expect(form.get('publish_to_tenant')).toBe('false')
      expect(form.get('candidate_id')).toBe('table')
      expect(wrapper.emitted('saved')).toHaveLength(1)
      expect(etl.autoIngestProgress).toHaveBeenCalledWith('batch-pick')
    } finally { wrapper.unmount() }
  })

  it('on archiveOnSelect, print/layout restrictions still allow private intake save', async () => {
    api.saveReviewedExcel.mockResolvedValue({ template_id: 'db:99', auto_ingest: { batch_id: 'batch-lim', status: 'running' } })
    const wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    try {
      const file = new File(['x'], 'limited.xlsx')
      const input = wrapper.find('input[type=file]')
      Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
      await input.trigger('change'); await flushPromises()
      const state = wrapper.vm.$.setupState as Record<string, unknown>
      state.classifications = [{ name: file.name, status: 'classified', confirmed: true, sheets: [], usage_restrictions: ['打印版式未验证'] }]
      state.file = file
      state.name = 'limited-tpl'
      state.review = { review_id: 'r-lim', sheets: [], cells: [], proposal: proposal('v1'), selected_region: { selection_basis: 'model_group' }, usage_restrictions: ['打印版式未验证'] }
      state.proposals = [proposal('v1')]
      state.templatePickerOpen = true
      await flushPromises()
      expect(state.publicationRestricted).toBe(true)
      await wrapper.findAll('button').find(b => b.text() === '使用此模板并入库')!.trigger('click')
      await flushPromises()
      expect(api.saveReviewedExcel).toHaveBeenCalledTimes(1)
      const form = api.saveReviewedExcel.mock.calls[0][0] as FormData
      expect(form.get('private_intake')).toBe('true')
      expect(form.get('publish_to_tenant')).toBe('false')
    } finally { wrapper.unmount() }
  })

  it('downloads a candidate workbook from the A4 picker', async () => {
    api.archiveClassifyExcel.mockResolvedValue({ name: 'cand.xlsx', status: 'classified', classification_id: 'c-cand', version: 'v1', confirmed: true, sheets: [{ sheet: 'S', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [{ range: 'A1:B2', labels: ['unknown'], checked_cells: 1, parent_heading: '', dependency_status: '待确认', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [], evidence: [] }] }] })
    api.confirmClassification.mockResolvedValue({ version: 'confirmed-version', confirmed: true, sheets: [{ sheet: 'S', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [{ range: 'A1:B2', labels: ['unknown'], checked_cells: 1, parent_heading: '', dependency_status: '待确认', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [], evidence: [] }] }] })
    api.reviewExcel.mockResolvedValue({ review_id: 'r-cand', sha256: 'sha', sheets: ['S'], cells: [], proposal: proposal('v1') })
    api.downloadReviewedCandidate.mockResolvedValue({ blob: async () => new Blob(['cand']) })
    api.downloadReviewedExcel.mockResolvedValue({ blob: async () => new Blob(['saved']) })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    try {
      const input = wrapper.get('input[type="file"][multiple]')
      Object.defineProperty(input.element, 'files', { configurable: true, value: [new File(['x'], 'cand.xlsx')] })
      await input.trigger('change'); await flushPromises()
      await wrapper.findAll('button').find(b => b.text() === '开始处理')!.trigger('click'); await flushPromises()
      const state = wrapper.vm.$.setupState as Record<string, unknown>
      state.name = 'cand-tpl'
      state.savedId = 'tpl-saved'
      await (state.downloadCandidate as (index: number) => Promise<void>)(0)
      await flushPromises()
      expect(api.downloadReviewedCandidate).toHaveBeenCalledWith('r-cand', 'v1', 'preserve')
      await (state.download as (id: string) => Promise<void>)('tpl-saved')
      await flushPromises()
      expect(api.downloadReviewedExcel).toHaveBeenCalledWith('tpl-saved')
      expect(click).toHaveBeenCalled()
    } finally {
      click.mockRestore()
      wrapper.unmount()
    }
  })

})
