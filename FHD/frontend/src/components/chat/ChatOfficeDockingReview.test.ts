import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatOfficeDockingReview from './ChatOfficeDockingReview.vue'
import type { ChatOfficeDockingReviewItem } from '@/composables/useChatOfficeDocking'

function reviewItem(overrides: Partial<ChatOfficeDockingReviewItem> = {}): ChatOfficeDockingReviewItem {
  return {
    id: 'delivery-1',
    fileName: '发货单/国圣化工.xlsx',
    employeeId: 'excel-full-read-employee',
    employeeLabel: 'Excel 读取员',
    kindLabel: 'Excel',
    status: 'ready',
    commitStatus: '',
    intentId: 'shipment_delivery',
    intentLabel: '送货单/发货单',
    intentSummary: '识别到送货单抬头与明细字段',
    databaseTargetLabel: '客户/产品/发货单',
    databaseAction: 'shipment_etl_execute',
    databaseDisabledReason: '',
    selectedTemplate: true,
    selectedDatabase: true,
    templateName: '国圣化工 · 发货单模板',
    templateScope: 'orders',
    templateTargetLabel: '发货单模板',
    templateCommitStatus: '',
    databaseCommitStatus: '',
    summary: '识别到送货单 1 张',
    warnings: [],
    error: '',
    outputFiles: [],
    excelAnalysis: { fields: ['购货单位', '品名', '数量'] },
    shipmentEtlPreview: {
      note_count: 1,
      notes: [{ sheet_name: '送货单', unit_name: '国圣化工', item_count: 2, total_amount: 200 }],
    },
    fieldNames: ['购货单位', '品名', '数量'],
    sampleRows: [],
    rowCount: 2,
    textPreview: '',
    ...overrides,
  }
}

function documentItem(overrides: Partial<ChatOfficeDockingReviewItem> = {}): ChatOfficeDockingReviewItem {
  return reviewItem({
    id: 'document-1',
    fileName: '说明.docx',
    employeeLabel: 'Word 全量读取员',
    kindLabel: 'Word',
    intentId: 'document',
    intentLabel: '普通办公文档',
    intentSummary: '已读取正文，建议归档为文档模板',
    databaseTargetLabel: '',
    databaseAction: '',
    databaseDisabledReason: '该文件不是可入库表格',
    selectedDatabase: false,
    templateName: '说明 · 文档模板',
    templateScope: '',
    templateTargetLabel: '文档模板',
    excelAnalysis: undefined,
    shipmentEtlPreview: undefined,
    fieldNames: [],
    sampleRows: [],
    rowCount: 0,
    textPreview: '这是一段 Word 正文。'.repeat(40),
    ...overrides,
  })
}

describe('ChatOfficeDockingReview', () => {
  it('presents one AI recommendation at a time', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [reviewItem(), documentItem()], processing: false },
    })

    expect(wrapper.get('.office-docking-review__head').text()).toContain('待审核 2 个 · 当前 1 / 2')
    expect(wrapper.text()).toContain('发货单/国圣化工.xlsx')
    expect(wrapper.text()).not.toContain('说明.docx')
    expect(wrapper.text()).toContain('我建议这样处理，可以吗？')
    expect(wrapper.text()).toContain('归档到模板库')
    expect(wrapper.text()).toContain('同步到 客户/产品/发货单')
  })

  it('advances to the next item after the current item is committed', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [reviewItem({ commitStatus: 'committed' }), documentItem()], processing: false },
    })

    expect(wrapper.get('.office-docking-review__head').text()).toContain('待审核 1 个 · 当前 2 / 2')
    expect(wrapper.text()).toContain('说明.docx')
    expect(wrapper.text()).not.toContain('发货单/国圣化工.xlsx')
  })

  it('allows the user to edit the suggested template name', async () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [reviewItem()], processing: false },
    })
    await wrapper.get('[aria-label="建议模板名称"]').setValue('国圣 · 标准发货模板')
    expect(wrapper.emitted('updateTemplateName')).toEqual([['delivery-1', '国圣 · 标准发货模板']])
  })

  it('emits separate template and database decisions', async () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [reviewItem()], processing: false },
    })
    const checkboxes = wrapper.findAll('input[type="checkbox"]')
    await checkboxes[0].setValue(false)
    await checkboxes[1].setValue(false)
    expect(wrapper.emitted('toggleTarget')).toEqual([
      ['delivery-1', 'template', false],
      ['delivery-1', 'database', false],
    ])
  })

  it('confirms only the current file and exposes a skip action', async () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [reviewItem(), documentItem()], processing: false },
    })
    await wrapper.get('button.btn-primary').trigger('click')
    await wrapper.findAll('button').find((button) => button.text().includes('跳过这个文件'))!.trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    expect(wrapper.emitted('skip')).toHaveLength(1)
    expect(wrapper.get('button.btn-primary').text()).toBe('按当前选择处理这个文件')
  })

  it('keeps documents template-only when no safe database target exists', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [documentItem()], processing: false },
    })
    expect(wrapper.text()).toContain('暂不写业务数据库')
    expect(wrapper.text()).toContain('该文件不是可入库表格')
    expect(wrapper.get('button.btn-primary').text()).toBe('确认归档这个模板')
    expect(wrapper.get('.office-docking-review__selection-hint').text()).toContain('仅处理当前文件')
  })

  it('disables execution while AI is still reading', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [reviewItem()], processing: true },
    })
    expect(wrapper.get('.office-docking-review__head').text()).toContain('正在读取 1 个文件')
    expect(wrapper.get('button.btn-primary').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.office-docking-review__selection-hint').text()).toContain('不会自动归档或写入')
  })

  it('shows target-level retry state without repeating a successful template archive', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: {
        items: [reviewItem({ commitStatus: 'failed', templateCommitStatus: 'committed', databaseCommitStatus: 'failed', error: '数据库暂不可用' })],
        processing: false,
      },
    })
    expect(wrapper.get('.office-docking-review__status').text()).toContain('处理失败，可重试')
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('失败，可重试')
    expect(wrapper.text()).toContain('数据库暂不可用')
  })

  it('distinguishes partial success from an automatically rolled-back target', () => {
    const partial = mount(ChatOfficeDockingReview, {
      props: {
        items: [reviewItem({ commitStatus: 'partial', templateCommitStatus: 'committed', databaseCommitStatus: 'failed' })],
        processing: false,
      },
    })
    expect(partial.get('.office-docking-review__status').text()).toContain('部分成功，可重试失败项')

    const rolledBack = mount(ChatOfficeDockingReview, {
      props: {
        items: [reviewItem({ commitStatus: 'failed', templateCommitStatus: 'rolled_back', databaseCommitStatus: 'failed' })],
        processing: false,
      },
    })
    expect(rolledBack.text()).toContain('失败后已自动回滚')
  })

  it('shows the structured shipment preview behind the recommendation', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [reviewItem()], processing: false },
    })
    expect(wrapper.get('.office-docking-review__preview-snippet').text()).toContain('送货单 1 张')
    expect(wrapper.get('.office-docking-review__shipment-notes').text()).toContain('国圣化工')
    expect(wrapper.get('.office-docking-review__preview-details summary').text()).toBe('查看送货单结构化预览')
  })

  it('shows a completion receipt after every item is handled or skipped', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: {
        items: [reviewItem({ commitStatus: 'committed' }), documentItem({ commitStatus: 'skipped' })],
        processing: false,
      },
    })
    expect(wrapper.get('.office-docking-review__complete').text()).toContain('审核完成')
    expect(wrapper.get('.office-docking-review__complete').text()).toContain('已处理 1 个，跳过 1 个')
    expect(wrapper.find('button.btn-primary').exists()).toBe(false)
  })
})
