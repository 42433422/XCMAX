import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReviewedExcelTemplate from './ReviewedExcelTemplate.vue'

const api = vi.hoisted(() => ({
  archiveClassifyExcel: vi.fn(), confirmClassification: vi.fn(), reviewExcel: vi.fn(),
  reviewedExcelIdentity: vi.fn(), previewReviewedIntake: vi.fn(),
}))
vi.mock('@/api/templatePreview', () => ({ default: api }))
vi.mock('@/api/xcmaxMarketProxy', () => ({ default: {
  llmResolveChatDefault: vi.fn().mockResolvedValue({ ok: true, provider: 'platform', model: 'synthetic-model' }),
} }))

const unavailableReason = '隐藏工作表暂不能作为独立模板提取，原件隐藏状态不变。'
const sheet = (name: string, sheet_state: 'visible' | 'hidden' | 'veryHidden') => ({
  sheet: name, sheet_state, processable: sheet_state === 'visible',
  processing_message: sheet_state === 'visible' ? '' : unavailableReason,
  labels: ['unknown'], checked_cells: 1, evidence: [], regions: [{
    range: 'A1:B2', labels: ['unknown'], checked_cells: 1, evidence: [], parent_heading: '',
    dependency_status: '待确认', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [],
  }],
})
type SyntheticSheet = ReturnType<typeof sheet>
const classified = (sheets: SyntheticSheet[], confirmed = false) => ({
  name: 'synthetic-hidden.xlsx', status: 'classified', classification_id: 'synthetic-hidden',
  version: confirmed ? 'confirmed-v2' : 'v1', confirmed, sheets,
})
const reviewed = () => ({
  review_id: 'visible-review', sha256: 'synthetic-sha', cells: [], sheets: ['Visible'],
  proposal: { version: 'v1', parent_version: null, candidates: [0, 1, 2].map(i => ({
    id: `candidate-${i}`, label: `候选${i + 1}`, explanation: '合成测试', clear: [],
  })), evidence: [], model: { status: 'not_called' } },
})
let wrapper: VueWrapper
let sheets: SyntheticSheet[]
const button = (text: string) => wrapper.findAll('button').find(el => el.text() === text)!
async function start() {
  const source = new File(['synthetic hidden-sheet fixture'], 'synthetic-hidden.xlsx')
  const input = wrapper.get('input[type=file]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: [source] })
  await input.trigger('change')
  await button('开始处理').trigger('click'); await flushPromises()
  return source
}
beforeEach(() => {
  vi.resetAllMocks()
  api.reviewedExcelIdentity.mockResolvedValue({ actor: '1:7', login_authorization: { operations: {
    classification: 'notice_not_published', template_candidates: 'notice_not_published',
  } } })
  api.archiveClassifyExcel.mockImplementation(async () => classified(sheets))
  api.confirmClassification.mockImplementation(async () => classified(sheets, true))
  api.reviewExcel.mockResolvedValue(reviewed())
  wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
})
afterEach(() => { wrapper.unmount(); vi.restoreAllMocks() })

describe('hidden-sheet intake selection', () => {
  it.each(['hidden', 'veryHidden'] as const)('skips the first %s sheet and keeps it unavailable without changing source state', async state => {
    sheets = [sheet('Hidden', state), sheet('Visible', 'visible')]
    const source = await start()
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    const form = api.reviewExcel.mock.calls[0][0] as FormData
    expect(form.get('file')).toBe(source)
    expect(form.get('region_sheet')).toBe('Visible')
    expect(form.get('region_range')).toBe('A1:B2')
    expect(button('Hidden / A1:B2').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain(unavailableReason)
    expect(sheets.map(item => item.sheet_state)).toEqual([state, 'visible'])
    const component = wrapper.vm.$.setupState as Record<string, unknown>
    expect(component.selectedRegion).toBe('Visible / A1:B2')
    ;(component.selectRegion as (i: number, j: number, k: number) => void)(0, 0, 0)
    await flushPromises()
    expect(component.selectedRegion).toBe('Visible / A1:B2')
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
  })

  it('keeps a hidden-only workbook blocked with a reason instead of previewing or unhiding it', async () => {
    sheets = [sheet('Hidden', 'hidden')]
    await start()
    expect(api.reviewExcel).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain(unavailableReason)
    expect(button('预览清理候选').attributes('disabled')).toBeDefined()
    expect(button('Hidden / A1:B2').attributes('disabled')).toBeDefined()
    expect(sheets[0].sheet_state).toBe('hidden')
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(0)
  })

  it('rejects a hidden coordinate even if a stale client selection is restored directly', async () => {
    sheets = [sheet('Hidden', 'hidden'), sheet('Visible', 'visible')]
    await start()
    const component = wrapper.vm.$.setupState as Record<string, unknown>
    component.selectedRegionCoordinates = { sheet: 'Hidden', range: 'A1:B2' }
    component.selectedRegion = 'Hidden / A1:B2'
    await flushPromises()
    expect(button('预览清理候选').attributes('disabled')).toBeDefined()
    await (component.preview as () => Promise<void>)()
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    expect(sheets[0].sheet_state).toBe('hidden')
  })
})
