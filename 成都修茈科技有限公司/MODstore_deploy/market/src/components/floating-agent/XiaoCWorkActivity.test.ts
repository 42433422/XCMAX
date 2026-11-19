import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../infrastructure/http/client'
import { xiaocAdminApi, type DeliveryFollowupDetail } from '../../application/xiaocAdminApi'
import XiaoCWorkActivity from './XiaoCWorkActivity.vue'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const detail: DeliveryFollowupDetail = {
  item: {
    ticket_id: 18,
    ticket_no: 'CS-18',
    title: '交付验收',
    stage_label: '待审批',
    expected_completion_at: null,
    following: false,
    needs_attention: true,
    attention_reason: '有审批待处理',
    can_resume: false,
    approval_id: '18',
    approval_title: '重跑验收前的内部检查',
    approval_reason: '上次检查报告缺少签字',
  },
  events: [
    { id: 'review-18', kind: 'receipt', label: '已收到检查回执', at: '2026-11-19T00:00:00Z', status: 'verified' },
    { id: 'action-18', kind: 'action', label: '申请敏感变更', at: '2026-11-19T00:00:00Z', status: 'pending_execution' },
  ],
}

function clickButton(wrapper: Pick<VueWrapper, 'findAll'>, label: string) {
  const button = wrapper.findAll('button').find((node) => node.text().trim() === label)
  if (!button) throw new Error(`找不到按钮：${label}`)
  return button.trigger('click')
}

describe('小 C 工作动态', () => {
  it('展示工单回执，并在用户看过审批内容且确认后提交实际审批', async () => {
    vi.spyOn(xiaocAdminApi, 'listFollowups').mockResolvedValue({ items: [detail.item] })
    vi.spyOn(xiaocAdminApi, 'followupDetail').mockResolvedValue(detail)
    const follow = vi.spyOn(xiaocAdminApi, 'follow').mockResolvedValue({
      ...detail,
      item: { ...detail.item, following: true },
    })
    const approve = vi.spyOn(xiaocAdminApi, 'approve').mockResolvedValue({
      ...detail,
      item: { ...detail.item, approval_id: null },
    })
    const confirm = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true)
    vi.stubGlobal('confirm', confirm)

    const wrapper = mount(XiaoCWorkActivity, { props: { ticketId: 18 } })
    await flushPromises()
    expect(xiaocAdminApi.followupDetail).toHaveBeenCalledWith(18)
    const timelineText = wrapper.get('.el-timeline').text().replace(/\s+/g, ' ')
    expect(timelineText).toContain('已收到检查回执 · 已核验')
    expect(timelineText).toContain('申请敏感变更 · 待执行')
    await clickButton(wrapper, '开始跟进')
    await flushPromises()
    expect(follow).toHaveBeenCalledWith(18, true)
    expect(wrapper.text()).toContain('停止跟进')
    await clickButton(wrapper, '确认审批')
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('上次检查报告缺少签字'))
    expect(approve).not.toHaveBeenCalled()
    await clickButton(wrapper, '确认审批')
    await flushPromises()
    expect(approve).toHaveBeenCalledWith(18, '18')
    expect(wrapper.text()).toContain('已记录审批')
    expect(wrapper.text()).not.toContain('已执行')
    wrapper.unmount()
  })

  it('记忆服务不可用时仍可查交付，恢复后按服务端结果保存和删除私有记忆', async () => {
    vi.spyOn(xiaocAdminApi, 'listFollowups').mockResolvedValue({ items: [detail.item] })
    vi.spyOn(xiaocAdminApi, 'listMemory')
      .mockRejectedValueOnce(new ApiError('unavailable', 503))
      .mockResolvedValue({ memories: [] })
    const entry = {
      memory_id: 'employee-pref-01',
      key: '交付口径',
      statement: '验收通过前不承诺发货日期',
      source: 'settings_ui',
      updated_at: '2026-11-19T00:00:00Z',
    }
    const save = vi.spyOn(xiaocAdminApi, 'saveMemory').mockResolvedValue({ memory: entry })
    const remove = vi.spyOn(xiaocAdminApi, 'deleteMemory').mockResolvedValue({ success: true })
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(true))

    const wrapper = mount(XiaoCWorkActivity)
    await clickButton(wrapper, '我的记忆')
    await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('暂时连不上记忆服务')
    await clickButton(wrapper, '交付跟进')
    await flushPromises()
    expect(wrapper.text()).toContain('交付验收')
    await clickButton(wrapper, '我的记忆')
    await flushPromises()
    await clickButton(wrapper, '新增记忆')
    await wrapper.get('input').setValue(` ${entry.key} `)
    await wrapper.get('textarea').setValue(entry.statement)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(save).toHaveBeenCalledWith({ key: entry.key, statement: entry.statement }, undefined)
    expect(wrapper.text()).toContain('你手动保存')
    await clickButton(wrapper, '删除')
    await flushPromises()
    expect(remove).toHaveBeenCalledWith(entry.memory_id)
    expect(wrapper.text()).toContain('还没有保存的记忆')
    wrapper.unmount()
  })
})
