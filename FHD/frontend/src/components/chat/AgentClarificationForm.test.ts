import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AgentClarificationForm from './AgentClarificationForm.vue'
const answer = vi.hoisted(() => vi.fn())
vi.mock('@/api/agentRuns', () => ({ agentRunsApi: { answerClarification: answer } }))
const question = { step_id: 's1', question: '请提供客户', fields: [{ key: 'unit_name', label: '客户单位', type: 'string' }] }
describe('clarification form', () => {
  beforeEach(() => { answer.mockReset() })
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
