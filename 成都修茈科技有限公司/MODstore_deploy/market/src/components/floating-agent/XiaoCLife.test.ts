import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ElSlider } from 'element-plus/es/components/slider/index'
import { ElPopover } from 'element-plus/es/components/popover/index'
import { ElInputNumber } from 'element-plus/es/components/input-number/index'
import { ElDialog } from 'element-plus/es/components/dialog/index'
import { xiaocLifeApi, type XiaoCLifeState, type XiaoCPortfolioLimits } from '../../application/xiaocLifeApi'
import { ApiError } from '../../infrastructure/http/client'
import XiaoCLifeControl from './XiaoCLifeControl.vue'
import XiaoCLifeActivity from './XiaoCLifeActivity.vue'

function snapshot(change: Partial<XiaoCLifeState> = {}): XiaoCLifeState {
  return {
    identity_id: 'enterprise-xiaoc',
    scope: 'enterprise',
    revision: 4,
    level: 4,
    paused: false,
    status: 'blocked',
    mission: '维护企业，探索新知识',
    activity: null,
    goals: [],
    interests: [],
    self_model: {},
    events: [],
    budget: { date: '2026-11-21', timezone: 'Asia/Shanghai', used_tokens: 0, reserved_tokens: 0, cycles: 0, exploration_tokens: 0 },
    policy: {
      daily_token_limit: 0,
      daily_cycle_limit: 4,
      exploration_percent: 20,
      wake_interval_seconds: 900,
      authorization_expires_at: null,
    },
    blockers: ['尚未设置后台模型预算'],
    updated_at: '2026-11-21T10:00:00Z',
    next_wake_at: null,
    ...change,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

const wrappers: VueWrapper[] = []
function track<T extends VueWrapper>(wrapper: T): T {
  wrappers.push(wrapper)
  return wrapper
}
async function click(wrapper: VueWrapper, label: string) {
  const button = wrapper.findAll('button').find((node) => node.text().trim() === label)
  if (!button) throw new Error(`找不到按钮：${label}`)
  await button.trigger('click')
}

beforeEach(() => {
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
})
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
})

describe('企业唯一小 C 管理界面', () => {
  it('未读到后端状态时禁用滑杆，不把不可用显示为在线', async () => {
    vi.spyOn(xiaocLifeApi, 'read').mockRejectedValue(new ApiError('unavailable', 503))
    const update = vi.spyOn(xiaocLifeApi, 'update')
    const wrapper = track(mount(XiaoCLifeControl, { props: { owner: 11 } }))
    await flushPromises()
    expect(wrapper.getComponent(ElSlider).props('disabled')).toBe(true)
    expect(wrapper.get('[role=alert]').text()).toContain('无法读取')
    expect(wrapper.text()).not.toContain('在线')
    expect(update).not.toHaveBeenCalled()
  })

  it('松开六档滑杆后提交企业版本，并按服务端回执显示等级', async () => {
    vi.spyOn(xiaocLifeApi, 'read').mockResolvedValue(snapshot())
    const next = deferred<XiaoCLifeState>()
    const update = vi.spyOn(xiaocLifeApi, 'update').mockReturnValue(next.promise)
    const wrapper = track(mount(XiaoCLifeControl, { props: { owner: 11 } }))
    await flushPromises()
    const slider = wrapper.getComponent(ElSlider)
    slider.vm.$emit('update:modelValue', 6)
    await flushPromises()
    expect(update).not.toHaveBeenCalled()
    slider.vm.$emit('change', 6)
    await flushPromises()
    expect(update).toHaveBeenCalledWith(4, { level: 6 })
    expect(wrapper.text()).toContain('L4 · 自治运营')
    expect(slider.props('disabled')).toBe(true)
    next.resolve(snapshot({ revision: 5, level: 6 }))
    await flushPromises()
    expect(wrapper.text()).toContain('L6 · 数字生命')
    expect(wrapper.text()).toContain('全企业生效')
  })

  it('输入框紧凑模式仅在确认后更新企业等级，等待服务端回执', async () => {
    vi.spyOn(xiaocLifeApi, 'read').mockResolvedValue(snapshot())
    const next = deferred<XiaoCLifeState>()
    const update = vi.spyOn(xiaocLifeApi, 'update').mockReturnValue(next.promise)
    const wrapper = track(mount(XiaoCLifeControl, { props: { owner: 11, compact: true }, global: { stubs: { teleport: true } } }))
    await flushPromises()
    const trigger = wrapper.get('[data-xiaoc-autonomy-trigger]')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(trigger.text()).toBe('自主任务')
    expect(trigger.attributes('title')).not.toContain('L4')
    await trigger.trigger('click')
    await flushPromises()
    expect(wrapper.getComponent(ElPopover).props('visible')).toBe(true)
    expect(wrapper.get('section').text()).toContain('L4 · 自治运营')
    expect(wrapper.get('.xiaoc-life-control__applied').text()).toBe('已应用')
    const slider = wrapper.getComponent(ElSlider)
    expect(slider.props('marks')).toEqual({ 1: 'L1', 2: 'L2', 3: 'L3', 4: 'L4', 5: 'L5', 6: 'L6' })
    slider.vm.$emit('update:modelValue', 6)
    slider.vm.$emit('change', 6)
    await flushPromises()
    expect(update).not.toHaveBeenCalled()
    expect(wrapper.get('[data-xiaoc-autonomy-trigger]').text()).toBe('自主任务')
    expect(wrapper.get('.xiaoc-life-control__preview').text()).toContain('预选 L6 · 数字生命')
    expect(wrapper.get('.xiaoc-life-control__applied').text()).toBe('当前已应用 L4 · 自治运营')
    expect(slider.attributes('data-autonomy-preview')).toBe('6')
    await click(wrapper, '确认切换')
    await flushPromises()
    expect(update).toHaveBeenCalledWith(4, { level: 6 })
    expect(wrapper.get('[data-xiaoc-autonomy-trigger]').text()).toBe('自主任务')
    next.resolve(snapshot({ revision: 5, level: 6 }))
    await flushPromises()
    expect(wrapper.get('[data-xiaoc-autonomy-trigger]').text()).toBe('自主任务')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    await trigger.trigger('click')
    await flushPromises()
    expect(wrapper.get('.xiaoc-life-control__preview').text()).toContain('L6 · 数字生命')
    expect(wrapper.get('.xiaoc-life-control__applied').text()).toBe('已应用')
  })

  it('紧凑模式拒绝读取失败时更改自治等级', async () => {
    vi.spyOn(xiaocLifeApi, 'read').mockRejectedValue(new ApiError('unavailable', 503))
    const update = vi.spyOn(xiaocLifeApi, 'update')
    const wrapper = track(mount(XiaoCLifeControl, { props: { owner: 11, compact: true }, global: { stubs: { teleport: true } } }))
    await flushPromises()
    const trigger = wrapper.get('[data-xiaoc-autonomy-trigger]')
    expect(trigger.text()).toBe('自主任务')
    expect(trigger.attributes('title')).toContain('状态待同步')
    await trigger.trigger('click')
    await flushPromises()
    expect(wrapper.getComponent(ElSlider).props('disabled')).toBe(true)
    expect(wrapper.findAll('button').find(node => node.text().trim() === '确认切换')?.attributes('disabled')).toBeDefined()
    expect(update).not.toHaveBeenCalled()
  })

  it('紧凑弹层 Escape 和外部点击关闭，丢弃未确认预选', async () => {
    vi.spyOn(xiaocLifeApi, 'read').mockResolvedValue(snapshot())
    const update = vi.spyOn(xiaocLifeApi, 'update')
    const wrapper = track(mount(XiaoCLifeControl, { props: { owner: 11, compact: true }, global: { stubs: { teleport: true } } }))
    await flushPromises()
    const trigger = wrapper.get('[data-xiaoc-autonomy-trigger]')
    await trigger.trigger('click')
    await flushPromises()
    wrapper.getComponent(ElSlider).vm.$emit('update:modelValue', 6)
    await flushPromises()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    await flushPromises()
    expect(trigger.attributes('aria-expanded')).toBe('false')
    await trigger.trigger('click')
    await flushPromises()
    expect(wrapper.getComponent(ElSlider).props('modelValue')).toBe(4)
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await flushPromises()
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(update).not.toHaveBeenCalled()
  })

  it('同一页面的控制与活动共用一次读取，窗口重新聚焦后同步后台降级', async () => {
    const read = vi.spyOn(xiaocLifeApi, 'read').mockResolvedValue(snapshot())
    const wrapper = track(
      mount(
        defineComponent({
          components: { XiaoCLifeControl, XiaoCLifeActivity },
          template: '<XiaoCLifeControl :owner="11" /><XiaoCLifeActivity :owner="11" />',
        }),
      ),
    )
    await flushPromises()
    expect(read).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('尚未设置后台模型预算')
    read.mockResolvedValue(snapshot({ revision: 5, level: 1, paused: true }))
    window.dispatchEvent(new Event('focus'))
    await flushPromises()
    expect(wrapper.text()).toContain('L1 · 对话助手')
    expect(wrapper.text()).toContain('自主活动已暂停')
    expect(wrapper.getComponent(ElSlider).props('modelValue')).toBe(1)
  })

  it('CAS 冲突回读新等级，旧选择不会自动覆盖另一管理员设置', async () => {
    vi.spyOn(xiaocLifeApi, 'read')
      .mockResolvedValueOnce(snapshot())
      .mockResolvedValue(snapshot({ revision: 7, level: 2 }))
    const update = vi.spyOn(xiaocLifeApi, 'update').mockRejectedValue(new ApiError('version conflict', 409))
    const wrapper = track(mount(XiaoCLifeControl, { props: { owner: 11 } }))
    await flushPromises()
    wrapper.getComponent(ElSlider).vm.$emit('change', 6)
    await flushPromises()
    expect(update).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('L2 · 智能执行')
    expect(wrapper.get('[role=alert]').text()).toContain('其他窗口更新')
    expect(wrapper.getComponent(ElSlider).props('modelValue')).toBe(2)
  })

  it('旧读取响应不会覆盖已保存的新模式', async () => {
    const delayed = deferred<XiaoCLifeState>()
    vi.spyOn(xiaocLifeApi, 'read').mockResolvedValueOnce(snapshot()).mockReturnValueOnce(delayed.promise)
    vi.spyOn(xiaocLifeApi, 'update').mockResolvedValue(snapshot({ revision: 5, paused: true }))
    const wrapper = track(mount(XiaoCLifeControl, { props: { owner: 11 } }))
    await flushPromises()
    window.dispatchEvent(new Event('focus'))
    await click(wrapper, '暂停自主活动')
    await flushPromises()
    delayed.resolve(snapshot())
    await flushPromises()
    expect(wrapper.text()).toContain('恢复自主活动')
    expect(wrapper.text()).toContain('自主活动已暂停')
  })

  it('停止后只能明确启动，原身份及持久状态版本来自服务端', async () => {
    vi.spyOn(xiaocLifeApi, 'read').mockResolvedValue(snapshot({ state_version: 10 }))
    const update = vi.spyOn(xiaocLifeApi, 'update')
      .mockResolvedValueOnce(snapshot({ revision: 5, state_version: 11, stopped: true, paused: true, status: 'stopped' }))
      .mockResolvedValueOnce(snapshot({ revision: 6, state_version: 12 }))
    const wrapper = track(mount(XiaoCLifeControl, { props: { owner: 11 } }))
    await flushPromises()
    await click(wrapper, '停止自主活动')
    await flushPromises()
    expect(update).toHaveBeenCalledWith(4, { stopped: true })
    expect(wrapper.text()).toContain('状态版本 11')
    expect(wrapper.text()).not.toContain('恢复自主活动')
    await click(wrapper, '启动自主活动')
    await flushPromises()
    expect(update).toHaveBeenCalledWith(5, { stopped: false, paused: false })
    expect(wrapper.text()).toContain('状态版本 12')
  })

  it('切换账号丢弃上一账号未完成的读取，退出视图后清掉轮询监听', async () => {
    const delayed = deferred<XiaoCLifeState>()
    const read = vi
      .spyOn(xiaocLifeApi, 'read')
      .mockReturnValueOnce(delayed.promise)
      .mockResolvedValue(snapshot({ revision: 8, level: 2 }))
    const wrapper = track(mount(XiaoCLifeControl, { props: { owner: 11 } }))
    await wrapper.setProps({ owner: 12 })
    await flushPromises()
    delayed.resolve(snapshot({ mission: '旧账号不应出现的信息', level: 6 }))
    await flushPromises()
    expect(wrapper.text()).toContain('L2 · 智能执行')
    expect(wrapper.text()).not.toContain('L6 · 数字生命')
    wrapper.unmount()
    wrappers.splice(wrappers.indexOf(wrapper), 1)
    const calls = read.mock.calls.length
    window.dispatchEvent(new Event('focus'))
    await flushPromises()
    expect(read).toHaveBeenCalledTimes(calls)
  })

  it('模型预算必须显式填写期限，授权提交保留编辑开始的版本', async () => {
    vi.spyOn(xiaocLifeApi, 'read').mockResolvedValue(snapshot())
    const update = vi.spyOn(xiaocLifeApi, 'update').mockResolvedValue(snapshot({ revision: 5 }))
    const wrapper = track(mount(XiaoCLifeActivity, { props: { owner: 11 }, global: { stubs: { teleport: true } } }))
    await flushPromises()
    await click(wrapper, '设置预算')
    wrapper.findAllComponents(ElInputNumber)[0].vm.$emit('update:modelValue', 1000)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(update).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请填写授权到期时间')
    const tomorrow = new Date(Date.now() + 86_400_000)
    const localTomorrow = new Date(tomorrow.getTime() - tomorrow.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
    await wrapper.get('input[type=datetime-local]').setValue(localTomorrow)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(update).toHaveBeenCalledWith(4, {
      policy: {
        ...snapshot().policy,
        daily_token_limit: 1000,
        authorization_expires_at: new Date(localTomorrow).toISOString(),
      },
    })
    expect(wrapper.text()).toContain('设置已保存')
    expect(wrapper.getComponent(ElDialog).props('modelValue')).toBe(false)
  })

  it('真实目标、兴趣与未知执行回执分别显示，不把排队或未知当作完成', async () => {
    vi.spyOn(xiaocLifeApi, 'read').mockResolvedValue(
      snapshot({
        goals: [{ id: 'goal-1', domain: 'exploration', title: '研究记忆召回', status: 'queued', evidence_refs: ['event-1'] }],
        interests: [{ topic: '长期记忆', confidence: 0.6, evidence_refs: ['event-1'] }],
        events: [
          {
            id: 'event-1',
            kind: 'reflection',
            summary: '试验尚无回执',
            status: 'unknown',
            evidence_refs: [],
            created_at: '2026-11-21T10:00:00Z',
            actual_tokens: null,
          },
        ],
      }),
    )
    const wrapper = track(mount(XiaoCLifeActivity, { props: { owner: 11 } }))
    await flushPromises()
    expect(wrapper.text()).toContain('自主探索 · 已排队')
    expect(wrapper.text()).toContain('长期记忆')
    expect(wrapper.text()).toContain('状态待核实（unknown）')
    expect(wrapper.text()).not.toContain('已完成')
    expect(wrapper.text()).toContain('北京时间')
  })

  it('目标只转成待审核提案，绑定服务器回执，不自动调用审批', async () => {
    const limits: XiaoCPortfolioLimits = {
      cost_cents: 1000,
      tokens: 50000,
      compute_seconds: 300,
      max_parallel: 1,
      max_failures: 2,
      stop_loss_cents: 1000,
      min_roi_bps: 0,
      observation_hours: 168,
      expires_at: new Date(Date.now() + 86_400_000).toISOString(),
      tariffs: [
        { provider: 'platform', model: 'model-1', input_cents_per_million: 120, output_cents_per_million: 430, source: '人工登记' },
      ],
    }
    const initial = snapshot({
      owner_user_id: 11,
      goals: [{ id: 'goal-1', domain: 'enterprise', title: '验证检索方案', status: 'proposed', evidence_refs: ['receipt-1'] }],
    })
    initial.policy = { ...initial.policy, employee_id: 'employee-1', portfolio_limits: limits, task_input: { date: '2026-11-21' } }
    vi.spyOn(xiaocLifeApi, 'read').mockResolvedValue(initial)
    const promote = vi.spyOn(xiaocLifeApi, 'promote').mockResolvedValue({
      decision_id: 'decision-1',
      life: { ...initial, revision: 5, goals: [{ ...initial.goals[0], decision_id: 'decision-1', status: 'awaiting_approval' }] },
    })
    const approve = vi.spyOn(xiaocLifeApi, 'approvePortfolio')
    const wrapper = track(mount(XiaoCLifeActivity, { props: { owner: 11 } }))
    await flushPromises()
    await click(wrapper, '转为企业提案')
    await flushPromises()
    expect(promote).toHaveBeenCalledExactlyOnceWith('goal-1', 4, 'employee-1', limits, { date: '2026-11-21' })
    expect(wrapper.text()).toContain('查看企业提案 decision-1')
    expect(wrapper.text()).toContain('企业任务 · 待审批')
    expect(approve).not.toHaveBeenCalled()
  })
})
