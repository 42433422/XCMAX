import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import ContextSummaryPills from './ContextSummaryPills.vue'

it.each([
  [undefined, []], ['  客户跟进  ', ['客户跟进']], [0, []],
  [[' 客户甲 ', '', null, 4], ['客户甲', '4']],
  [{ items: [' 报价 ', false, '订单'], text: '不应替代条目' }, ['报价', '订单']],
  [{ items: [' '], text: ' 待确认 ', label: '备用' }, ['待确认']],
  [{ items: 'invalid', label: ' 财务 ' }, ['财务']], [{}, []],
])('renders only usable, trimmed summary pills for %j', async (summary, expected) => {
  const wrapper = mount(ContextSummaryPills, { props: { summary } })
  expect(wrapper.findAll('.context-summary-pill').map(node => node.text())).toEqual(expected)
  await wrapper.setProps({ summary: { text: '已更新' } })
  expect(wrapper.findAll('.context-summary-pill').map(node => node.text())).toEqual(['已更新'])
  wrapper.unmount()
})
