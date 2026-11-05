import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AgentClarificationForm from './AgentClarificationForm.vue'
const answer = vi.hoisted(() => vi.fn())
vi.mock('@/api/agentRuns', () => ({ agentRunsApi: { answerClarification: answer } }))
const question = { step_id: 's1', question: '请提供客户', fields: [{ key: 'unit_name', label: '客户单位', type: 'string' }] }
describe('clarification form', () => {
  beforeEach(() => { answer.mockReset() })
  it('submits a numeric answer for only the missing quotation line field', async () => {
    answer.mockResolvedValue({ success: true })
    const wrapper = mount(AgentClarificationForm, { props: { runId: 'quote-run', question: {
      step_id: 'price-step', question: '请补充单价', fields: [{ key: 'items.0.unit_price', label: 'A100 · 单价', type: 'number' }],
    } } })
    expect(wrapper.text()).toContain('A100 · 单价')
    await wrapper.get('input').setValue('25.5')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(answer).toHaveBeenCalledWith('quote-run', { step_id: 'price-step', parameters: { 'items.0.unit_price': 25.5 } })
  })
  it('submits only entered fields to the exact run and step', async () => {
    answer.mockResolvedValue({ success: true })
    const wrapper = mount(AgentClarificationForm, { props: { runId: 'r1', question } })
    await wrapper.get('input').setValue('客户甲')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(answer).toHaveBeenCalledWith('r1', { step_id: 's1', parameters: { unit_name: '客户甲' } })
    expect(wrapper.text()).toContain('已提交')
    await wrapper.get('form').trigger('submit')
    expect(answer).toHaveBeenCalledTimes(1)
  })
  it('retains the answer and allows retry on failure', async () => {
    answer.mockRejectedValue(new Error('稍后重试'))
    const wrapper = mount(AgentClarificationForm, { props: { runId: 'r1', question } })
    await wrapper.get('input').setValue('客户甲')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toBe('稍后重试')
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('客户甲')
    expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
  })
})
