import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatOfficeDockingReview from './ChatOfficeDockingReview.vue'
import type { ChatOfficeDockingReviewItem } from '@/composables/useChatOfficeDocking'

function item(overrides: Partial<ChatOfficeDockingReviewItem> = {}): ChatOfficeDockingReviewItem {
  return {
    id: 'excel-1',
    fileName: '宗南.xlsx',
    employeeId: 'elt',
    employeeLabel: 'ELT',
    kindLabel: '办公文件',
    status: 'ready',
    commitStatus: '',
    intentId: 'pending',
    intentLabel: 'ELT 解析',
    intentSummary: '',
    databaseTargetLabel: '',
    databaseAction: '',
    databaseDisabledReason: '',
    selectedKnowledge: false,
    selectedDatabase: false,
    summary: 'ELT 已解析',
    warnings: [],
    error: '',
    outputFiles: [],
    knowledgeText: '',
    fieldNames: [],
    sampleRows: [],
    rowCount: 1,
    textPreview: '',
    worksheetTemplates: [
      { id: '人员', label: '人员', sheet: '人员' },
      { id: '部门', label: '部门', sheet: '部门' },
    ],
    selectedTemplateIndex: -1,
    pipeline: 'elt',
    ...overrides,
  }
}

describe('ChatOfficeDockingReview', () => {
  it('treats worksheet templates as optional capsules and saves into approval', async () => {
    const wrapper = mount(ChatOfficeDockingReview, { props: { items: [item()], processing: false } })
    expect(wrapper.text()).toContain('选择模板')
    expect(wrapper.text()).toContain('保存并提交入库')
    await wrapper.get('button.office-docking-review__capsule').trigger('click')
    expect(wrapper.emitted('pickTemplate')).toBeUndefined()
    const choices = wrapper.findAll('.office-docking-review__picker button')
    await choices[2].trigger('click')
    expect(wrapper.emitted('pickTemplate')?.[0]).toEqual(['excel-1', 1])
    await wrapper.get('.btn-primary').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('can clear the template without blocking save', async () => {
    const wrapper = mount(ChatOfficeDockingReview, {
      props: { items: [item({ selectedTemplateIndex: 0 })], processing: false },
    })
    expect(wrapper.text()).toContain('人员')
    await wrapper.get('button.office-docking-review__capsule').trigger('click')
    await wrapper.get('.office-docking-review__picker button').trigger('click')
    expect(wrapper.emitted('pickTemplate')?.[0]).toEqual(['excel-1', -1])
  })
})
