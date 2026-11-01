import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import ReviewedExcelTemplate from './ReviewedExcelTemplate.vue'

const api = vi.hoisted(() => ({
  archiveClassifyExcel: vi.fn(), confirmClassification: vi.fn(), reviewExcel: vi.fn(),
  refineReviewedExcel: vi.fn(), previewReviewedIntake: vi.fn(),
  reviewedExcelIdentity: vi.fn(), analyzeClassification: vi.fn(), autoSlices: vi.fn(), recentClassifications: vi.fn(),
}))
vi.mock('@/api/templatePreview', () => ({ default: api }))
vi.mock('@/api/xcmaxMarketProxy', () => ({ default: {
  llmResolveChatDefault: vi.fn().mockResolvedValue({ ok: true, provider: 'platform', model: 'default-chat' }),
} }))

const classified = (name = 'synthetic.xlsx', confirmed = false) => ({
  name, status: 'classified', classification_id: name, version: 'v1', confirmed,
  sheets: [{ sheet: 'Sheet1', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [{
    range: 'A1:B2', labels: ['unknown'], checked_cells: 1, evidence: [], parent_heading: '',
    dependency_status: '待确认', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [],
  }] }],
})
const reviewed = (id = 'local-review') => ({
  review_id: id, sha256: 'synthetic-sha', cells: [], sheets: ['Sheet1'],
  proposal: { version: 'v1', parent_version: null, candidates: [0, 1, 2].map(i => ({
    id: `candidate-${i}`, label: `候选${i + 1}`, explanation: '本地建议', clear: [],
  })), evidence: [], model: { status: 'not_called' } },
})
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(finish => { resolve = finish })
  return { promise, resolve }
}
let wrapper: VueWrapper
const button = (text: string) => wrapper.findAll('button').find(el => el.text() === text)!
async function stageFile(name = 'synthetic.xlsx') {
  const source = new File(['synthetic source, unchanged'], name, { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const input = wrapper.get('input[type=file]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: [source] })
  await input.trigger('change')
  return source
}
async function start() { await button('开始处理').trigger('click'); await flushPromises() }
function bytes(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}
const modelSlice = (index = 0, sheet = 'Sheet1') => ({ index, basis: 'model_group', confirmed: false, sha256: `slice-${index}`, filename: `synthetic-${index}.xlsx`, fragments: [{ sheet, range: 'A1:B2' }] })
function enableModelPipeline(slices = [modelSlice()]) {
  api.reviewedExcelIdentity.mockResolvedValue({ actor: '1:7', login_authorization: { status: 'authorized', operations: { classification: 'authorized', template_candidates: 'authorized' } } })
  api.analyzeClassification.mockResolvedValue({ version: 'model-v2', model_status: 'returned', sheets: classified().sheets })
  api.autoSlices.mockResolvedValue({ slices })
  const result = reviewed()
  api.reviewExcel.mockResolvedValue({ ...result, selected_region: { selection_basis: 'model_group' }, proposal: { ...result.proposal, model: { status: 'returned', login_authorization: { status: 'authorized' } } } })
}
beforeEach(() => {
  vi.resetAllMocks()
  updateProductReadAccountScope({ tenantId: 1, localUserId: 'inline-A', accountKind: 'local' })
  api.archiveClassifyExcel.mockImplementation(async (form: FormData) => classified((form.get('file') as File).name))
  api.confirmClassification.mockImplementation(async (id: string) => ({ ...classified(id, true), version: 'v2' }))
  api.reviewExcel.mockResolvedValue(reviewed())
  api.reviewedExcelIdentity.mockResolvedValue({ actor: '1:7', login_authorization: { status: 'notice_not_published', operations: { classification: 'notice_not_published', template_candidates: 'notice_not_published' } } })
  wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
})
afterEach(() => { wrapper.unmount(); vi.restoreAllMocks() })

describe('inline ELT processing', () => {
  it('shows progress immediately, ignores duplicate start clicks and keeps the source unchanged', async () => {
    const pending = deferred<ReturnType<typeof classified>>()
    api.archiveClassifyExcel.mockReturnValueOnce(pending.promise)
    const confirm = vi.spyOn(window, 'confirm')
    const source = await stageFile(), original = await bytes(source)
    await wrapper.get('.elt-composer__input').setValue('保留原范围')
    const startButton = button('开始处理').element
    startButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    startButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(wrapper.get('[role=status]').text()).toContain('归档及分类 1/1')
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    expect(wrapper.findAll('.elt-bubble--user').filter(el => el.text().startsWith('整理要求：'))).toHaveLength(1)
    pending.resolve(classified()); await flushPromises()
    expect(api.confirmClassification).toHaveBeenCalledTimes(1)
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[role=status]').text()).toBe('当前仅生成本地规则候选，平台模型尚未启用。')
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(3)
    expect(wrapper.findAll('input[type=checkbox]')).toHaveLength(0)
    expect(button('关闭')).toBeUndefined()
    expect(confirm).not.toHaveBeenCalled()
    expect((api.reviewExcel.mock.calls[0][0] as FormData).get('file')).toBe(source)
    expect(await bytes(source)).toBe(original)
  })

  it('uses local rules and preserves unexecuted feedback as a draft without silently granting consent', async () => {
    await stageFile(); await start()
    const form = api.reviewExcel.mock.calls[0][0] as FormData
    expect([form.get('model_opt_in'), form.get('sample_authorized'), form.get('own_file_authorized')]).toEqual(['false', 'false', 'false'])
    expect(form.get('use_login_notice')).toBe('false')
    await wrapper.get('.elt-composer__input').setValue('保留备注')
    await button('发送').trigger('click'); await flushPromises()
    expect(api.refineReviewedExcel).not.toHaveBeenCalled()
    expect(wrapper.findAll('input[type=checkbox]')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('合成或公开样本')
    expect(wrapper.text()).not.toContain('我有权授权')
    expect(wrapper.get('[role=alert]').text()).toBe('模型尚未启用，整理要求未执行，草稿已保留。')
    expect((wrapper.get('.elt-composer__input').element as HTMLTextAreaElement).value).toBe('保留备注')
    expect(wrapper.findAll('.elt-bubble--user').map(el => el.text())).not.toContain('整理要求：保留备注')
  })

  it.each(['notice_not_published', 'login_notice_required'] as const)('keeps %s local and puts its exact reason in folded diagnostics', async status => {
    const result = reviewed()
    api.reviewExcel.mockResolvedValueOnce({ ...result, proposal: { ...result.proposal, model: {
      status: 'not_called', login_authorization: { status, version: 'synthetic-notice', purpose: 'elt_bounded_preview' },
    } } })
    await stageFile(); await start()
    const diagnostics = wrapper.get('.reviewed-template__diagnostics')
    expect((diagnostics.element as HTMLDetailsElement).open).toBe(false)
    expect(diagnostics.get('summary').text()).toBe('处理诊断')
    expect(diagnostics.text()).toContain(status === 'notice_not_published' ? '条款尚未发布' : '会话没有完整的分类与模板候选授权')
    expect(diagnostics.text()).toContain('本次未调用模型')
    expect(wrapper.get('[role=status]').text()).toBe('当前仅生成本地规则候选，平台模型尚未启用。')
    await wrapper.get('.elt-composer__input').setValue('保留备注')
    await button('发送').trigger('click'); await flushPromises()
    expect(api.refineReviewedExcel).not.toHaveBeenCalled()
    expect(wrapper.findAll('input[type=checkbox]')).toHaveLength(0)
  })

  it('uses a verified server login grant for feedback without inventing per-file or sample consent', async () => {
    const result = reviewed(), login_authorization = { status: 'authorized', version: 'synthetic-published', purpose: 'elt_bounded_preview', provider: 'platform', model: 'synthetic-model' }
    const authorized = { ...result.proposal, model: { status: 'returned', login_authorization } }
    api.reviewExcel.mockResolvedValueOnce({ ...result, proposal: authorized })
    api.refineReviewedExcel.mockResolvedValueOnce({ proposal: { ...authorized, version: 'v2', parent_version: 'v1' } })
    await stageFile(); await start()
    const state = wrapper.vm.$.setupState as Record<string, unknown>
    state.initialModel = true; state.sampleAuthorized = false; state.templateOwnFileAuthorized = false
    await flushPromises()
    expect(button('预览清理候选').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('.reviewed-template__diagnostics').text()).toContain('模型已返回候选建议')
    expect(wrapper.get('[role=status]').text()).toBe('平台模型候选已生成，请核对。')
    expect((wrapper.get('.reviewed-template__diagnostics').element as HTMLDetailsElement).open).toBe(false)
    await wrapper.get('.elt-composer__input').setValue('保留备注')
    await button('发送').trigger('click'); await flushPromises()
    expect(api.refineReviewedExcel).toHaveBeenCalledTimes(1)
    const form = api.refineReviewedExcel.mock.calls[0][0] as FormData
    expect(form.get('use_login_notice')).toBe('true')
    expect([form.get('consent'), form.get('sample_authorized'), form.get('own_file_authorized')]).toEqual(['false', 'false', 'false'])
    expect(form.get('feedback')).toBe('保留备注')
    expect(wrapper.findAll('input[type=checkbox]')).toHaveLength(0)
    await button('查看版本 1').trigger('click'); await flushPromises()
    await wrapper.get('.elt-composer__input').setValue('旧版本不要再发')
    await button('发送').trigger('click'); await flushPromises()
    expect(api.refineReviewedExcel).toHaveBeenCalledTimes(1)
    await stageFile('new-ungranted.xlsx'); await start()
    await wrapper.get('.elt-composer__input').setValue('新文件没有授权')
    await button('发送').trigger('click'); await flushPromises()
    expect(api.refineReviewedExcel).toHaveBeenCalledTimes(1)
  })

  it('reports an unavailable authorized model inside diagnostics without claiming generation succeeded with AI', async () => {
    const result = reviewed()
    api.reviewExcel.mockResolvedValueOnce({ ...result, proposal: { ...result.proposal, model: {
      status: 'unavailable', login_authorization: { status: 'authorized', version: 'synthetic-published' },
    } } })
    await stageFile(); await start()
    expect(wrapper.get('.reviewed-template__diagnostics').text()).toContain('模型调用未完成，当前显示本地规则候选')
    expect(wrapper.get('[role=status]').text()).toBe('平台模型处理未完成，当前显示本地规则候选，请查看处理诊断。')
  })

  it('retries candidate failures in place without rearchiving or enabling a model', async () => {
    await stageFile(); await start()
    api.reviewExcel.mockRejectedValueOnce(new Error('候选服务暂不可用，请重试')).mockResolvedValueOnce(reviewed('retry-review'))
    await button('预览清理候选').trigger('click'); await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('候选服务暂不可用')
    expect(wrapper.text()).toContain('候选生成未完成')
    await button('预览清理候选').trigger('click'); await flushPromises()
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    for (const call of api.reviewExcel.mock.calls.slice(1)) {
      const form = call[0] as FormData
      expect([form.get('model_opt_in'), form.get('sample_authorized'), form.get('own_file_authorized')]).toEqual(['false', 'false', 'false'])
    }
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
  })

  it('recovers a print-boundary rejection only after choosing the explicit derived-copy retry', async () => {
    api.reviewExcel.mockRejectedValueOnce(new Error('打印区域跨越所选文档，请明确选择所选片段作为派生打印区域'))
    const source = await stageFile(), original = await bytes(source)
    await start()
    expect((api.reviewExcel.mock.calls[0][0] as FormData).get('print_area_mode')).toBe('source')
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(0)
    await button('按所选片段生成副本并重试（原件不变）').trigger('click'); await flushPromises()
    const form = api.reviewExcel.mock.calls[1][0] as FormData
    expect(form.get('print_area_mode')).toBe('selected')
    expect(form.get('file')).toBe(source)
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(3)
    expect(wrapper.findAll('input[type=checkbox]')).toHaveLength(0)
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
    expect(button('按所选片段生成副本并重试（原件不变）')).toBeUndefined()
    expect(await bytes(source)).toBe(original)
  })

  it('retries archive failure with the same request identity and offers inline recovery when confirmation is incomplete', async () => {
    api.archiveClassifyExcel.mockRejectedValueOnce(new Error('归档暂不可用'))
    api.confirmClassification.mockResolvedValueOnce({ ...classified(), message: '请核对片段后再次确认' })
    await stageFile(); await start()
    const requestKey = (api.archiveClassifyExcel.mock.calls[0][0] as FormData).get('request_key')
    expect(requestKey).toBeTruthy()
    await button('重试未完成文件').trigger('click'); await flushPromises()
    expect((api.archiveClassifyExcel.mock.calls[1][0] as FormData).get('request_key')).toBe(requestKey)
    expect(api.reviewExcel).not.toHaveBeenCalled()
    expect(wrapper.find('.classification-region').isVisible()).toBe(true)
    expect(button('确认分类并继续').isVisible()).toBe(true)
    expect(wrapper.text()).not.toContain('合成或公开样本')
    expect(wrapper.text()).not.toContain('我有权授权')
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
  })

  it('discards late candidates after an account change and clears consent for the new file', async () => {
    const pending = deferred<ReturnType<typeof reviewed>>()
    await stageFile(); await start()
    api.reviewExcel.mockReturnValueOnce(pending.promise)
    await button('预览清理候选').trigger('click'); await flushPromises()
    updateProductReadAccountScope({ tenantId: 1, localUserId: 'inline-B', accountKind: 'local' })
    await flushPromises(); await stageFile('new-synthetic.xlsx'); await start()
    pending.resolve(reviewed('stale-account-review')); await flushPromises()
    const state = wrapper.vm.$.setupState as Record<string, unknown>
    expect((state.review as { review_id: string }).review_id).toBe('local-review')
    const form = api.reviewExcel.mock.calls.at(-1)![0] as FormData
    expect((form.get('file') as File).name).toBe('new-synthetic.xlsx')
    expect([form.get('model_opt_in'), form.get('own_file_authorized')]).toEqual(['false', 'false'])
    expect(wrapper.get('.elt-bubble--user').text()).toBe('已选择 1 个文件：new-synthetic.xlsx')
  })

  it('switches a classified batch file in place without reusing its previous candidate or rearchiving', async () => {
    const sources = ['first.xlsx', 'second.xlsx'].map(name => new File(['synthetic'], name))
    const input = wrapper.get('input[type=file]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: sources })
    await input.trigger('change'); await start()
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(2)
    await button('second.xlsx').trigger('click'); await flushPromises()
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(0)
    await button('预览清理候选').trigger('click'); await flushPromises()
    const form = api.reviewExcel.mock.calls.at(-1)![0] as FormData
    expect(form.get('file')).toBe(sources[1])
    expect(form.get('classification_id')).toBe('second.xlsx')
    expect([form.get('model_opt_in'), form.get('sample_authorized'), form.get('own_file_authorized')]).toEqual(['false', 'false', 'false'])
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
  })

  it('runs authorized model classification → slices → candidates once for duplicate Start clicks', async () => {
    enableModelPipeline()
    const pending = deferred<{ version: string; model_status: string; sheets: ReturnType<typeof classified>['sheets'] }>()
    api.analyzeClassification.mockReturnValueOnce(pending.promise)
    await stageFile()
    const startButton = button('开始处理').element
    startButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    startButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    expect(api.reviewExcel).not.toHaveBeenCalled()
    const analysis = api.analyzeClassification.mock.calls[0][1] as FormData
    expect(analysis.get('use_login_notice')).toBe('true')
    expect([analysis.get('sample_authorized'), analysis.get('own_file_authorized')]).toEqual([null, null])
    pending.resolve({ version: 'model-v2', model_status: 'returned', sheets: classified().sheets }); await flushPromises()
    expect(api.confirmClassification).not.toHaveBeenCalled()
    expect(api.autoSlices).toHaveBeenCalledWith('synthetic.xlsx', 'model-v2')
    const preview = api.reviewExcel.mock.calls[0][0] as FormData
    expect([preview.get('auto_slice_index'), preview.get('use_login_notice'), preview.get('model_opt_in'), preview.get('sample_authorized'), preview.get('own_file_authorized')]).toEqual(['0', 'true', 'false', 'false', 'false'])
    expect(api.autoSlices.mock.invocationCallOrder[0]).toBeGreaterThan(api.analyzeClassification.mock.invocationCallOrder[0])
    expect(api.reviewExcel.mock.invocationCallOrder[0]).toBeGreaterThan(api.autoSlices.mock.invocationCallOrder[0])
    await start()
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
  })

  it('offers multiple model slices inline and generates only the selected one', async () => {
    enableModelPipeline([modelSlice(0), modelSlice(1)])
    await stageFile(); await start()
    expect(api.reviewExcel).not.toHaveBeenCalled()
    const choices = wrapper.findAll('button').filter(el => el.text() === '用此单据生成模板')
    expect(choices).toHaveLength(2)
    await choices[1].trigger('click'); await flushPromises()
    expect((api.reviewExcel.mock.calls[0][0] as FormData).get('auto_slice_index')).toBe('1')
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
  })

  it('limits signed-session model analysis to the currently selected file in an archived batch', async () => {
    enableModelPipeline()
    const input = wrapper.get('input[type=file]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: ['first.xlsx', 'second.xlsx'].map(name => new File(['synthetic'], name)) })
    await input.trigger('change'); await start()
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(2)
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    expect(api.analyzeClassification.mock.calls[0][0]).toBe('first.xlsx')
    expect(api.autoSlices).toHaveBeenCalledWith('first.xlsx', 'model-v2')
    expect((api.reviewExcel.mock.calls[0][0] as FormData).get('file')).toHaveProperty('name', 'first.xlsx')
    expect(api.confirmClassification).not.toHaveBeenCalled()
  })

  it('blocks hidden model slices and preserves their original visibility metadata', async () => {
    enableModelPipeline([modelSlice(0, 'Hidden')])
    const visible = classified().sheets[0]
    const sheets = [{ ...visible, sheet: 'Hidden', sheet_state: 'hidden', processable: false }, visible]
    api.archiveClassifyExcel.mockResolvedValueOnce({ ...classified(), sheets })
    api.analyzeClassification.mockResolvedValueOnce({ version: 'model-v2', model_status: 'returned', sheets: [{ ...visible, sheet: 'Hidden' }, visible] })
    await stageFile(); await start()
    expect(api.reviewExcel).not.toHaveBeenCalled()
    expect(button('用此单据生成模板').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('没有可处理的模型文档切片')
  })

  it.each(['classification', 'template_candidates'] as const)('does not treat a missing %s scope as a complete model pipeline', async missing => {
    enableModelPipeline()
    api.reviewedExcelIdentity.mockResolvedValueOnce({ actor: '1:7', login_authorization: { status: 'authorized', operations: { classification: missing === 'classification' ? 'login_notice_required' : 'authorized', template_candidates: missing === 'template_candidates' ? 'login_notice_required' : 'authorized' } } })
    api.reviewExcel.mockResolvedValueOnce(reviewed())
    await stageFile(); await start()
    expect(api.analyzeClassification).not.toHaveBeenCalled()
    expect((api.reviewExcel.mock.calls[0][0] as FormData).get('use_login_notice')).toBe('false')
    expect(wrapper.get('[role=status]').text()).toContain('平台模型尚未启用')
    expect(wrapper.get('.reviewed-template__diagnostics').text()).toContain('没有完整的分类与模板候选授权')
  })

  it('stops visibly when identity verification fails instead of generating an unverified candidate', async () => {
    api.reviewedExcelIdentity.mockRejectedValueOnce(new Error('授权状态读取失败'))
    await stageFile(); await start()
    expect(api.reviewExcel).not.toHaveBeenCalled()
    expect(wrapper.get('[role=alert]').text()).toContain('授权状态读取失败')
  })

  it('never resends an unknown classification outcome or falls back to rule candidates', async () => {
    enableModelPipeline()
    api.analyzeClassification.mockRejectedValueOnce(new Error('模型分类响应中断'))
    api.recentClassifications.mockResolvedValue({ files: [] })
    await stageFile(); await start(); await start()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    expect(api.autoSlices).not.toHaveBeenCalled()
    expect(api.reviewExcel).not.toHaveBeenCalled()
    expect(wrapper.get('[role=alert]').text()).toContain('结果未知')
  })

  it('requires an explicit new-budget retry after a known failed classification exhausts its round', async () => {
    enableModelPipeline()
    api.archiveClassifyExcel.mockResolvedValueOnce({ ...classified(), checkpoint: { phase: 'failed', version: 'v1', completed: 0, total: 1, max_calls: 1, calls_in_round: 1, message: '失败待确认' } })
    await stageFile(); await start()
    expect(api.analyzeClassification).not.toHaveBeenCalled()
    await button('确认新一轮预算并重试模型分类').trigger('click'); await flushPromises()
    const form = api.analyzeClassification.mock.calls[0][1] as FormData
    expect([form.get('retry_authorized'), form.get('continue_authorized'), form.get('use_login_notice')]).toEqual(['true', 'true', 'true'])
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    expect(wrapper.findAll('input[type=checkbox]')).toHaveLength(0)
  })

  it('continues a paused classification round only on the explicit Start operation', async () => {
    enableModelPipeline()
    api.archiveClassifyExcel.mockResolvedValueOnce({ ...classified(), checkpoint: { phase: 'paused', version: 'v1', completed: 1, total: 2, max_calls: 1, calls_in_round: 1, message: '等待继续' } })
    await stageFile()
    expect(api.analyzeClassification).not.toHaveBeenCalled()
    await start()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    const form = api.analyzeClassification.mock.calls[0][1] as FormData
    expect([form.get('continue_authorized'), form.get('retry_authorized'), form.get('use_login_notice')]).toEqual(['true', null, 'true'])
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
  })

  it('drops a late authorized classification when the account changes before slicing', async () => {
    enableModelPipeline()
    const pending = deferred<{ version: string; model_status: string; sheets: ReturnType<typeof classified>['sheets'] }>()
    api.analyzeClassification.mockReturnValueOnce(pending.promise)
    await stageFile(); await start()
    updateProductReadAccountScope({ tenantId: 1, localUserId: 'pipeline-B', accountKind: 'local' })
    await flushPromises()
    api.reviewedExcelIdentity.mockResolvedValue({ actor: '1:8' }); api.reviewExcel.mockResolvedValue(reviewed('new-account'))
    await stageFile('new-account.xlsx'); await start()
    pending.resolve({ version: 'stale', model_status: 'returned', sheets: classified().sheets }); await flushPromises()
    expect(api.autoSlices).not.toHaveBeenCalled()
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    expect((api.reviewExcel.mock.calls[0][0] as FormData).get('file')).toHaveProperty('name', 'new-account.xlsx')
  })
})
