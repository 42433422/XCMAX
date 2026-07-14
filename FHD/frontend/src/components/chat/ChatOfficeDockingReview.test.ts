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

describe('ChatOfficeDockingReview', () => {
  it('shows a compact Word excerpt and clearly states knowledge-only behavior', () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [wordItem()], processing: false },
    })
    const snippet = wrapper.get('.office-docking-review__preview-snippet')
    expect(snippet.text().length).toBeLessThanOrEqual(221)
    expect(wrapper.get('.office-docking-review__preview-details').attributes('open')).toBeUndefined()
    expect(wrapper.get('.office-docking-review__selection-hint').text()).toContain('不会修改业务数据库')
    expect(wrapper.get('button.btn-primary').text()).toBe('确认加入知识库')
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
})
