import { DOMWrapper, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ElInputNumber } from 'element-plus/es/components/input-number/index'
import { ElSelect } from 'element-plus/es/components/select/index'
import { employees } from '../../api/employees'
import { llm } from '../../api/llm'
import { xiaocLifeApi, type XiaoCLifePolicy, type XiaoCPortfolioTemplate } from '../../application/xiaocLifeApi'
import { ApiError } from '../../infrastructure/http/client'
import XiaoCLifeTaskBudget from './XiaoCLifeTaskBudget.vue'
import XiaoCLifeProposal from './XiaoCLifeProposal.vue'

const policy: XiaoCLifePolicy = {
  daily_token_limit: 0,
  daily_cycle_limit: 4,
  exploration_percent: 20,
  wake_interval_seconds: 900,
  authorization_expires_at: null,
}
function proposal(expires = Date.now() + 86_400_000): XiaoCPortfolioTemplate {
  return {
    decision_id: 'decision-1',
    goal: '验证召回质量',
    status: 'proposed',
    proposal_sha256: 'a'.repeat(64),
    limits: {
      cost_cents: 1000,
      tokens: 10000,
      compute_seconds: 300,
      max_parallel: 1,
      max_failures: 2,
      stop_loss_cents: 1000,
      min_roi_bps: 0,
      observation_hours: 168,
      expires_at: new Date(expires).toISOString(),
      tariffs: [
        { provider: 'platform', model: 'model-1', input_cents_per_million: 100, output_cents_per_million: 300, source: '已登记计提费率' },
      ],
    },
    opportunities: [
      {
        employee_id: 'employee-1',
        title: '执行验证',
        task: '仅在隔离环境验证召回',
        source_refs: ['receipt-1'],
        input_data: { date: '2026-11-21', scope: 'daily' },
        execution_binding: {
          pack_id: 'employee-1',
          version: '2.0.1',
          manifest_sha256: 'm'.repeat(64),
          archive_sha256: 'a'.repeat(64),
          config_sha256: 'c'.repeat(64),
          input_sha256: 'i'.repeat(64),
        },
      },
    ],
  }
}
const wrappers: VueWrapper[] = []
function track<T extends VueWrapper>(wrapper: T) {
  wrappers.push(wrapper)
  return wrapper
}
// Exercise form policy with real Element Plus inputs; modal teleport behavior is covered below.
const globals = { stubs: { ElDialog: { template: '<section><slot /></section>' } } }
async function click(wrapper: VueWrapper, label: string) {
  const button = wrapper.findAll('button').find((node) => node.text().trim() === label)
  if (!button) throw new Error(`找不到按钮：${label}`)
  await button.trigger('click')
}

beforeEach(() => {
  vi.spyOn(employees, 'listEmployees').mockResolvedValue([{ id: 'employee-1', name: '研发员工' }])
  vi.spyOn(llm, 'llmCatalog').mockResolvedValue({ providers: [{ provider: 'platform', label: '平台', models: ['model-1'] }] })
  vi.spyOn(llm, 'llmStatus').mockResolvedValue({ providers: [{ provider: 'platform', has_platform_key: true }] })
  vi.spyOn(xiaocLifeApi, 'templates').mockResolvedValue({ items: [] })
})
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  document.body.innerHTML = ''
})

describe('企业任务预算与原提案审批接线', () => {
  it('真实 dialog 与真实下拉菜单在 body 中挂载和选择，不替换 Teleport', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    track(mount(XiaoCLifeTaskBudget, { props: { policy, busy: false }, attachTo: host }))
    await flushPromises()
    const body = new DOMWrapper(document.body)
    const select = body.findAll('.el-select')
    await select[0].get('.el-select__wrapper').trigger('click')
    await flushPromises()
    await select[0].get('[role=option]').trigger('click')
    await flushPromises()
    await select[1].get('.el-select__wrapper').trigger('click')
    await flushPromises()
    await select[1].get('[role=option]').trigger('click')
    await flushPromises()
    expect(select[0].get('[aria-selected=true]').text()).toContain('研发员工')
    expect(select[1].get('[aria-selected=true]').text()).toContain('platform / model-1')
    expect(body.get('[role=dialog]').text()).toContain('保存模板不批准任务')
  })

  it('没有历史模板时可新建，但模型缺价不默认免费，保存模板不执行或批准', async () => {
    const approve = vi.spyOn(xiaocLifeApi, 'approvePortfolio')
    const wrapper = track(mount(XiaoCLifeTaskBudget, { props: { policy, busy: false }, global: globals }))
    await flushPromises()
    const selects = wrapper.findAllComponents(ElSelect)
    selects[0].vm.$emit('update:modelValue', 'employee-1')
    await flushPromises()
    selects[1].vm.$emit('change', JSON.stringify(['platform', 'model-1']))
    await flushPromises()
    const numbers = wrapper.findAllComponents(ElInputNumber)
    numbers[0].vm.$emit('update:modelValue', 12.34)
    numbers[1].vm.$emit('update:modelValue', 50000)
    const tomorrow = new Date(Date.now() + 86_400_000)
    await wrapper
      .get('input[type=datetime-local]')
      .setValue(new Date(tomorrow.getTime() - tomorrow.getTimezoneOffset() * 60_000).toISOString().slice(0, 16))
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.emitted('save')).toBeUndefined()
    expect(wrapper.get('[role=alert]').text()).toContain('明确填写')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('{}')
    await wrapper.get('textarea').setValue('{"date":"2026-11-21"}')
    numbers[3].vm.$emit('update:modelValue', 1.2)
    numbers[4].vm.$emit('update:modelValue', 4.3)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.emitted('save')?.[0]?.[0]).toMatchObject({
      employee_id: 'employee-1',
      task_input: { date: '2026-11-21' },
      portfolio_limits: {
        cost_cents: 1234,
        stop_loss_cents: 1234,
        tokens: 50000,
        max_parallel: 1,
        tariffs: [
          {
            provider: 'platform',
            model: 'model-1',
            input_cents_per_million: 120,
            output_cents_per_million: 430,
            source: '管理员配置的计提费率，非供应商账单',
          },
        ],
      },
    })
    expect(approve).not.toHaveBeenCalled()
  })

  it('复制到期组合只带入边界，必须重新明确有效期才能保存', async () => {
    vi.mocked(xiaocLifeApi.templates).mockResolvedValue({ items: [proposal(Date.now() - 60_000)] })
    const wrapper = track(mount(XiaoCLifeTaskBudget, { props: { policy, busy: false }, global: globals }))
    await flushPromises()
    wrapper.findAllComponents(ElSelect)[0].vm.$emit('change', 'decision-1')
    await flushPromises()
    expect(JSON.parse((wrapper.get('textarea').element as HTMLTextAreaElement).value)).toEqual({ date: '2026-11-21', scope: 'daily' })
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('save')).toBeUndefined()
    expect(wrapper.text()).toContain('未来的任务有效期')
    expect(wrapper.text()).toContain('不继承旧提案审批')
  })

  it.each([
    ['[]', '必须是 JSON 对象'],
    ['{', '不是有效的 JSON'],
    ['{"api_key":"do-not-send"}', '不能包含密钥'],
    ['{"allow_external_write":true}', '不能包含密钥'],
    [JSON.stringify({ brief: '汉'.repeat(22000) }), '64000 字节'],
  ])('员工业务输入先校验，非法参数不提交（第 %# 项）', async (raw, expected) => {
    const wrapper = track(mount(XiaoCLifeTaskBudget, { props: { policy, busy: false }, global: globals }))
    await flushPromises()
    await wrapper.get('textarea').setValue(raw)
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('save')).toBeUndefined()
    expect(wrapper.get('[role=alert]').text()).toContain(expected)
  })

  it('可信目录登记价格可换算，未配置的平台模型不进入选择器', async () => {
    vi.mocked(llm.llmCatalog).mockResolvedValue({
      providers: [
        {
          provider: 'platform',
          label: '平台',
          models: ['model-1'],
          models_detailed: [
            { id: 'model-1', pricing: { source: 'db', effective_input_per_1k: 0.00123, effective_output_per_1k: 0.00456 } },
          ],
        },
        { provider: 'unconfigured', label: '无密钥', models: ['unavailable'] },
      ],
    })
    const wrapper = track(mount(XiaoCLifeTaskBudget, { props: { policy, busy: false }, global: globals }))
    await flushPromises()
    const selects = wrapper.findAllComponents(ElSelect)
    expect(wrapper.text()).not.toContain('unavailable')
    selects[1].vm.$emit('change', JSON.stringify(['platform', 'model-1']))
    await flushPromises()
    const numbers = wrapper.findAllComponents(ElInputNumber)
    expect(numbers[3].props('modelValue')).toBe(1.23)
    expect(numbers[4].props('modelValue')).toBe(4.56)
  })

  it('实际审核展示任务边界，明确勾选后仅批准读到的提案摘要', async () => {
    const original = proposal()
    vi.spyOn(xiaocLifeApi, 'portfolio')
      .mockResolvedValueOnce(original)
      .mockResolvedValue({ ...original, status: 'approved' })
    const approve = vi.spyOn(xiaocLifeApi, 'approvePortfolio').mockResolvedValue({ decision_id: original.decision_id, status: 'approved' })
    const wrapper = track(mount(XiaoCLifeProposal, { props: { decisionId: original.decision_id }, global: globals }))
    await flushPromises()
    expect(wrapper.text()).toContain('仅在隔离环境验证召回')
    expect(wrapper.text()).toContain('receipt-1')
    expect(wrapper.text()).toContain('"scope": "daily"')
    expect(wrapper.text()).toContain('employee-1 / 2.0.1')
    expect(wrapper.text()).toContain('c'.repeat(64))
    await click(wrapper, '批准这个提案')
    expect(approve).not.toHaveBeenCalled()
    await wrapper.get('input[type=checkbox]').setValue(true)
    await click(wrapper, '批准这个提案')
    await flushPromises()
    expect(approve).toHaveBeenCalledExactlyOnceWith(original.decision_id, original.proposal_sha256)
    expect(wrapper.text()).toContain('审批已记录')
    expect(wrapper.text()).not.toContain('已完成')
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('提案摘要冲突后重新读回，不使用新摘要自动重试批准', async () => {
    const original = proposal()
    vi.spyOn(xiaocLifeApi, 'portfolio')
      .mockResolvedValueOnce(original)
      .mockResolvedValue({ ...original, proposal_sha256: 'b'.repeat(64) })
    const approve = vi.spyOn(xiaocLifeApi, 'approvePortfolio').mockRejectedValue(new ApiError('hash changed', 409))
    const wrapper = track(mount(XiaoCLifeProposal, { props: { decisionId: original.decision_id }, global: globals }))
    await flushPromises()
    await wrapper.get('input[type=checkbox]').setValue(true)
    await click(wrapper, '批准这个提案')
    await flushPromises()
    expect(approve).toHaveBeenCalledExactlyOnceWith(original.decision_id, original.proposal_sha256)
    expect(wrapper.text()).toContain('不会自动批准新版本')
    expect((wrapper.get('input[type=checkbox]').element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.emitted('changed')).toBeUndefined()
  })

  it('缺少冻结输入或员工合同的旧提案不能批准', async () => {
    const old = proposal()
    old.opportunities[0].execution_binding = undefined
    vi.spyOn(xiaocLifeApi, 'portfolio').mockResolvedValue(old)
    const approve = vi.spyOn(xiaocLifeApi, 'approvePortfolio')
    const wrapper = track(mount(XiaoCLifeProposal, { props: { decisionId: old.decision_id }, global: globals }))
    await flushPromises()
    expect(wrapper.text()).toContain('暂不能批准')
    expect(wrapper.find('input[type=checkbox]').exists()).toBe(false)
    expect(approve).not.toHaveBeenCalled()
  })
})
