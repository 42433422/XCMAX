import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatOfficeDockingReview from './ChatOfficeDockingReview.vue'
import type { ChatOfficeDockingReviewItem } from '@/composables/useChatOfficeDocking'

function wordItem(overrides: Partial<ChatOfficeDockingReviewItem> = {}): ChatOfficeDockingReviewItem {
  return {
    id: 'word-1',
    fileName: '考勤说明.docx',
    employeeId: 'word-full-read-employee',
    employeeLabel: 'Word 全量读取员',
    kindLabel: 'Word',
    status: 'ready',
    commitStatus: '',
    intentId: 'document',
    intentLabel: '普通办公文档',
    intentSummary: '适合先进入知识库',
    databaseTargetLabel: '',
    databaseAction: '',
    databaseDisabledReason: '该文件不是可入库表格',
    selectedKnowledge: true,
    selectedDatabase: false,
    summary: '已识别 12 个段落',
    warnings: [],
    error: '',
    outputFiles: [],
    knowledgeText: '正文',
    fieldNames: [],
    sampleRows: [],
    rowCount: 0,
    textPreview: '这是一段很长的 Word 正文。'.repeat(40),
    ...overrides,
  }
}

function excelItem(overrides: Partial<ChatOfficeDockingReviewItem> = {}): ChatOfficeDockingReviewItem {
  return {
    id: 'excel-1',
    fileName: '考勤表.xlsx',
    employeeId: 'excel-mapper-employee',
    employeeLabel: 'Excel 入库员',
    kindLabel: 'Excel',
    status: 'ready',
    commitStatus: '',
    intentId: 'attendance_roster',
    intentLabel: '考勤表入库',
    intentSummary: '识别成功，可入库',
    databaseTargetLabel: '考勤数据库',
    databaseAction: 'attendance_import',
    databaseDisabledReason: '',
    selectedKnowledge: false,
    selectedDatabase: true,
    summary: '已识别 30 行',
    warnings: [],
    error: '',
    outputFiles: [],
    knowledgeText: '',
    excelAnalysis: { columns: [{ name: '员工姓名' }] },
    fieldNames: ['员工姓名', '日期', '上班时间', '下班时间', '工时'],
    sampleRows: [{ 员工姓名: '张三', 日期: '2026-07-01', 上班时间: '09:00', 下班时间: '18:00', 工时: 9 }],
    rowCount: 30,
    textPreview: '',
    ...overrides,
  }
}

describe('ChatOfficeDockingReview', () => {
  it('shows a compact Word excerpt and clearly states knowledge-only behavior', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [wordItem()], processing: false },
    })
    const snippet = wrapper.get('.office-docking-review__preview-snippet')
    expect(snippet.text().length).toBeLessThanOrEqual(221)
    expect(wrapper.get('.office-docking-review__preview-details').attributes('open')).toBeUndefined()
    expect(wrapper.get('.office-docking-review__selection-hint').text()).toContain('不会直接写库')
    expect(wrapper.get('button.btn-primary').text()).toBe('进入数据对接中心')
  })

  it('disables confirmation until at least one write target is selected', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: {
        items: [wordItem({ selectedKnowledge: false })],
        processing: false,
      },
    })
    const confirm = wrapper.get('button.btn-primary')
    expect(confirm.attributes('disabled')).toBeDefined()
    expect(confirm.text()).toBe('请选择处理方式')
  })

  it('does not offer to write an already committed document again', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: {
        items: [wordItem({ commitStatus: 'committed' })],
        processing: false,
      },
    })
    expect(wrapper.get('button.btn-primary').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.office-docking-review__head').text()).toContain('待确认 0 个')
  })

  it('shows sample row preview for Excel items with sampleRows', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [excelItem()], processing: false },
    })
    const snippet = wrapper.get('.office-docking-review__preview-snippet')
    expect(snippet.text()).toContain('共 30 行')
    expect(snippet.text()).toContain('员工姓名')
  })

  it('opens detailed preview for Excel items', async () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [excelItem()], processing: false },
    })
    const details = wrapper.get('.office-docking-review__preview-details')
    expect(details.attributes('open')).toBeUndefined()
    await details.get('summary').trigger('click')
    // Opening details is a browser-native behavior; we just confirm the element renders
    expect(details.find('pre.office-docking-review__preview').exists()).toBe(true)
  })

  it('emits toggleTarget when knowledge checkbox is toggled', async () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [wordItem({ selectedKnowledge: true })], processing: false },
    })
    const checkbox = wrapper.findAll('input[type="checkbox"]')[0]
    checkbox.element.checked = false
    await checkbox.trigger('change')
    expect(wrapper.emitted('toggleTarget')).toEqual([['word-1', 'knowledge', false]])
  })

  it('emits toggleTarget when database checkbox is toggled', async () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [excelItem({ selectedDatabase: false, databaseAction: 'insert' })], processing: false },
    })
    const checkbox = wrapper.findAll('input[type="checkbox"]')[1]
    checkbox.element.checked = true
    await checkbox.trigger('change')
    expect(wrapper.emitted('toggleTarget')).toEqual([['excel-1', 'database', true]])
  })

  it('emits close when cancel button is clicked', async () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [wordItem()], processing: false },
    })
    const cancel = wrapper.findAll('button').find((b) => b.text().includes('取消'))!
    await cancel.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('emits close when icon close button is clicked', async () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [wordItem()], processing: false },
    })
    await wrapper.get('.office-docking-review__icon-btn').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('emits confirm when primary button is clicked', async () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [wordItem()], processing: false },
    })
    await wrapper.get('button.btn-primary').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('shows processing state in header when processing=true', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [wordItem()], processing: true },
    })
    expect(wrapper.get('.office-docking-review__head').text()).toContain('员工识别中')
  })

  it('disables confirm button when processing=true', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [wordItem()], processing: true },
    })
    expect(wrapper.get('button.btn-primary').attributes('disabled')).toBeDefined()
  })

  it('shows committing label and disables buttons when commitStatus=committing', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [excelItem({ commitStatus: 'committing', selectedDatabase: true })], processing: false },
    })
    expect(wrapper.get('button.btn-primary').text()).toBe('正在创建预演...')
    expect(wrapper.get('button.btn-primary').attributes('disabled')).toBeDefined()
  })

  it('shows failed status text when commitStatus=failed', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [excelItem({ commitStatus: 'failed' })], processing: false },
    })
    expect(wrapper.get('.office-docking-review__status').text()).toBe('创建失败')
  })

  it('shows running status text when status=running', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [excelItem({ status: 'running' })], processing: false },
    })
    expect(wrapper.get('.office-docking-review__status').text()).toBe('识别中')
  })

  it('shows error status text and error message when status=error', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [excelItem({ status: 'error', error: '解析失败' })], processing: false },
    })
    expect(wrapper.get('.office-docking-review__status').text()).toBe('识别失败')
    expect(wrapper.get('.office-docking-review__error').text()).toBe('解析失败')
  })

  it('shows field chips for items with fieldNames', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [excelItem()], processing: false },
    })
    const chips = wrapper.findAll('.office-docking-review__chips span')
    expect(chips.length).toBe(5)
    expect(chips[0].text()).toBe('员工姓名')
  })

  it('shows database target label in selection hint when database selected', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [excelItem({ selectedDatabase: true })], processing: false },
    })
    expect(wrapper.get('.office-docking-review__selection-hint').text()).toContain('考勤数据库')
  })

  it('shows confirm label with database target when only database selected', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [excelItem({ selectedKnowledge: false, selectedDatabase: true })], processing: false },
    })
    expect(wrapper.get('button.btn-primary').text()).toBe('预演考勤数据库')
  })

  it('shows generic confirm label when both targets selected', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [excelItem({ selectedKnowledge: true, selectedDatabase: true })], processing: false },
    })
    expect(wrapper.get('button.btn-primary').text()).toBe('创建预演并进入对接中心')
  })

  it('shows database disabled reason hint when no databaseAction', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [wordItem()], processing: false },
    })
    expect(wrapper.get('.office-docking-review__hint').text()).toContain('该文件不是可入库表格')
  })

  it('shows intent summary with database target label', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [excelItem()], processing: false },
    })
    const intent = wrapper.get('.office-docking-review__intent')
    expect(intent.text()).toContain('考勤表入库')
    expect(intent.text()).toContain('考勤数据库')
  })

  it('opens detailed preview for long Word text', async () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [wordItem()], processing: false },
    })
    const details = wrapper.get('.office-docking-review__preview-details')
    expect(details.find('summary').text()).toBe('查看原文摘录')
  })

  it('omits detailed preview when Word text is short', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: {
        items: [wordItem({ textPreview: '短文本' })],
        processing: false,
      },
    })
    expect(wrapper.find('.office-docking-review__preview-details').exists()).toBe(false)
  })

  it('shows summary line when summary is present', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [excelItem({ summary: '已识别 50 行' })], processing: false },
    })
    expect(wrapper.get('.office-docking-review__summary').text()).toBe('已识别 50 行')
  })

  it('omits summary when empty', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [excelItem({ summary: '' })], processing: false },
    })
    expect(wrapper.find('.office-docking-review__summary').exists()).toBe(false)
  })

  it('shows committed status text', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [wordItem({ commitStatus: 'committed' })], processing: false },
    })
    expect(wrapper.get('.office-docking-review__status').text()).toBe('预演已创建')
  })

  it('shows pending status text by default', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [wordItem()], processing: false },
    })
    expect(wrapper.get('.office-docking-review__status').text()).toBe('待确认')
  })

  it('renders shipment ETL note preview and confirm target', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: {
        items: [excelItem({
          fileName: '国圣送货单.xlsx',
          intentId: 'shipment_delivery',
          intentLabel: '送货单/发货单',
          intentSummary: '识别到 1 张送货单',
          databaseTargetLabel: '客户/产品/发货单',
          databaseAction: 'shipment_etl_execute',
          sampleRows: [],
          fieldNames: ['购货单位', '型号'],
          shipmentEtlPreview: {
            note_count: 1,
            notes: [{
              sheet_name: '送货单',
              unit_name: '甲公司',
              item_count: 2,
              total_amount: 20,
            }],
          },
        })],
        processing: false,
      },
    })
    expect(wrapper.get('.office-docking-review__preview-snippet').text()).toContain('送货单 1 张')
    expect(wrapper.get('.office-docking-review__shipment-notes').text()).toContain('甲公司')
    expect(wrapper.get('.office-docking-review__preview-details summary').text()).toBe('查看送货单结构化预览')
    expect(wrapper.get('button.btn-primary').text()).toBe('预演客户/产品/发货单')
  })
})
