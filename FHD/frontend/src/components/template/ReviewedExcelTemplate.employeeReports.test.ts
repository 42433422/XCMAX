import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import ReviewedExcelTemplate from './ReviewedExcelTemplate.vue'

const api = vi.hoisted(() => ({
  archiveClassifyExcel: vi.fn(), reviewedExcelIdentity: vi.fn(), analyzeClassification: vi.fn(),
  autoSlices: vi.fn(), reviewExcel: vi.fn(), refineReviewedExcel: vi.fn(), previewReviewedIntake: vi.fn(), saveReviewedExcel: vi.fn(),
}))
vi.mock('@/api/templatePreview', () => ({ default: api }))
vi.mock('@/api/xcmaxMarketProxy', () => ({ default: { llmResolveChatDefault: vi.fn() } }))

const sheet = { sheet: 'Sheet1', sheet_state: 'visible', processable: true, labels: ['template'], checked_cells: 2, evidence: [], regions: [{ range: 'A1:B2', labels: ['template'], checked_cells: 2, evidence: [], parent_heading: '', dependency_status: 'ready', needs_confirmation: false, header_cells: [], merged_ranges: [], possible_shared_context: [] }] }
const layout = (value: string) => [{ sheet: 'Sheet1', widths: [20], rows: [{ height: 20, cells: [{ cell: 'A1', value, formula: false, rowspan: 1, colspan: 1, bold: false, italic: false, font_size: 11, font_color: '', fill: '', align: 'left' }] }], truncated: false }]
function reviewed(name: string) {
  const candidates = [0, 1, 2].map(i => ({ id: `${name}-${i}`, label: `方案${i + 1}`, explanation: `${name}候选${i + 1}`, clear: [{ sheet: 'Sheet1', cell: 'A2' }] }))
  return { review_id: `review-${name}`, sha256: `sha-${name}`, layout: layout(`${name}原件`), cells: [], sheets: ['Sheet1'], proposal: { version: 'v1', parent_version: null, candidates, evidence: [], model: { status: 'returned' }, result_previews: candidates.map(candidate => ({ candidate_id: candidate.id, sha256: candidate.id, layout: layout(candidate.label), layout_truncated: false })) } }
}
function intake(knowledge: Record<string, unknown>, business: Record<string, unknown>, detection: Record<string, unknown> = { degraded: false }) {
  return { intake: { run_id: 'run-1', mod_id: '', candidate_sha256: 'candidate', detection, knowledge, business: { id: 'run-1', target_type: 'shipment_records', status: 'preview_ready', preview_revision: 'revision', summary: { new: 2, update: 0, skip: 0, error: 0, executed: 0 }, ...business } } }
}
let wrapper: VueWrapper
const button = (label: string) => wrapper.findAll('button').find(el => el.text() === label)!
beforeEach(() => {
  vi.resetAllMocks()
  updateProductReadAccountScope({ tenantId: 1, localUserId: 'report-A', accountKind: 'local' })
  api.archiveClassifyExcel.mockImplementation(async (form: FormData) => ({ name: (form.get('file') as File).name, status: 'classified', classification_id: 'class-first.xlsx', version: 'archive-v1', sheets: [sheet] }))
  api.reviewedExcelIdentity.mockResolvedValue({ actor: '1:7' })
  api.analyzeClassification.mockResolvedValue({ version: 'model-v2', model_status: 'returned', sheets: [sheet] })
  api.autoSlices.mockResolvedValue({ slices: [{ index: 0, basis: 'model_group', confirmed: false, sha256: 'slice-0', filename: '送货单.xlsx', display_name: '送货单', fragments: [{ sheet: 'Sheet1', range: 'A1:B2' }] }] })
  api.reviewExcel.mockResolvedValue(reviewed('送货单'))
  api.previewReviewedIntake.mockResolvedValue(intake(
    { action: 'new', documents: 1, degraded: false, lane: 'knowledge', content: '演示客户乙购买螺母五桶' },
    { details: { entities: { customers: 0, purchase_units: 1, products: 2, records: 2 } } },
  ))
  wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
})
afterEach(() => wrapper.unmount())

async function openAndChoose() {
  Object.defineProperty(wrapper.get('input[type=file]').element, 'files', { configurable: true, value: [new File(['synthetic workbook'], 'note.xlsx')] })
  await wrapper.get('input[type=file]').trigger('change')
  await button('开始处理').trigger('click')
  await flushPromises()
  await wrapper.get('[data-document-key]').trigger('click')
  await flushPromises()
  await wrapper.get('.reviewed-template__select-candidate').trigger('click')
  await flushPromises()
}

describe('template capsule with database and knowledge reports', () => {
  it('keeps the template capsule and shows imported counts plus organized knowledge', async () => {
    await openAndChoose()
    const capsule = wrapper.get('.reviewed-template__candidate-capsule')
    expect(capsule.element.tagName).toBe('BUTTON')
    expect(capsule.classes()).toContain('reviewed-template__candidate-capsule')
    expect(capsule.attributes('aria-haspopup')).toBe('dialog')
    expect(capsule.text()).toContain('送货单')
    const database = wrapper.get('[data-employee=database]')
    const knowledge = wrapper.get('[data-employee=knowledge]')
    expect(database.classes()).not.toContain('reviewed-template__candidate-capsule')
    expect(database.element.tagName).toBe('ARTICLE')
    expect(database.text()).toContain('数据库导入员')
    expect(database.text()).toContain('写入业务数据库')
    expect(database.text()).toContain('客户 0')
    expect(database.text()).toContain('购买单位 1')
    expect(database.text()).toContain('产品 2')
    expect(database.text()).toContain('明细 2')
    expect(knowledge.text()).toContain('知识整理员')
    expect(knowledge.text()).toContain('本次整理 1 份文档。')
    expect(knowledge.text()).toContain('演示客户乙购买螺母五桶')
    expect(wrapper.get('[aria-label=工作情况回报]').findAll('article')).toHaveLength(2)
  })

  it('does not claim success for a degraded database or knowledge line', async () => {
    api.previewReviewedIntake.mockResolvedValue(intake(
      { action: 'error', documents: 0, degraded: true, lane: 'knowledge', content: '产品名称' },
      { details: { entities: { customers: 1, purchase_units: 0, products: 0, records: 1 } } },
      { degraded: true },
    ))
    await openAndChoose()
    const database = wrapper.get('[data-employee=database]')
    const knowledge = wrapper.get('[data-employee=knowledge]')
    expect(database.text()).toContain('数据库导入员没有做完。')
    expect(knowledge.text()).toContain('知识整理员没有做完。')
    expect(`${database.text()}\n${knowledge.text()}`).not.toMatch(/本次入库|本次整理|已写入|成功|产品名称/)
    expect(wrapper.get('.reviewed-template__candidate-capsule').text()).toContain('送货单')
  })
})
