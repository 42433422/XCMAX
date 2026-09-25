import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ApprovalHubView from '../../../admin-console/src/views/ApprovalHubView.vue'

const fetchOwnerWorkOrders = vi.fn()
const decideOwnerWorkOrder = vi.fn()
const appAlert = vi.fn().mockResolvedValue(undefined)
const appPrompt = vi.fn().mockResolvedValue('已复核证据')

vi.mock('@/api/xcmaxAdmin', () => ({
  xcmaxAdminApi: {
    fetchOwnerWorkOrders: (...args: unknown[]) => fetchOwnerWorkOrders(...args),
    decideOwnerWorkOrder: (...args: unknown[]) => decideOwnerWorkOrder(...args),
  },
}))

vi.mock('@/utils/appDialog', () => ({
  appAlert: (...args: unknown[]) => appAlert(...args),
  appPrompt: (...args: unknown[]) => appPrompt(...args),
}))

const lockedOrder = {
  wo_id: 'WO-20260926-0001',
  status: 'in_dev',
  reason: '客户无法提交产品问题工单',
  context: {
    customer_user_id: 'xcagi-enterprise-demo',
    client_instance_id: 'test-client-01',
    product_version: '1.0.0.5',
    git_sha: 'a'.repeat(40),
    platform: 'macOS',
    expected: '创建工单并上传支持包',
    actual: '没有工单编号和支持包摘要',
  },
  gates: { repro: 'RED' },
  can_decide: false,
}

const readyOrder = {
  ...lockedOrder,
  wo_id: 'WO-20260926-0002',
  gates: { repro: 'RED', fix: 'FIX_VALIDATED_IN_DEV', owner_instance: 'OWNER_INSTANCE_VERIFIED' },
  can_decide: true,
}

describe('ApprovalHubView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchOwnerWorkOrders.mockResolvedValue({ ok: true, count: 1, items: [lockedOrder] })
    decideOwnerWorkOrder.mockResolvedValue({
      ok: true,
      wo_id: readyOrder.wo_id,
      decision: 'approved',
      actor: 'owner:42',
    })
  })

  it('shows customer and evidence context while keeping incomplete work orders locked', async () => {
    const wrapper = mount(ApprovalHubView)
    await flushPromises()

    expect(wrapper.text()).toContain('产品问题工单审批')
    expect(wrapper.text()).toContain(lockedOrder.wo_id)
    expect(wrapper.text()).toContain('xcagi-enterprise-demo')
    expect(wrapper.text()).toContain('客户无法提交产品问题工单')
    expect(wrapper.text()).toContain('决策锁定')
    expect(wrapper.findAll('.drawer-actions')).toHaveLength(0)
    expect(fetchOwnerWorkOrders).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('records an Owner decision only when all required receipts unlock the order', async () => {
    fetchOwnerWorkOrders.mockResolvedValue({ ok: true, count: 1, items: [readyOrder] })
    const wrapper = mount(ApprovalHubView)
    await flushPromises()

    await wrapper.find('.btn-primary').trigger('click')
    await flushPromises()

    expect(decideOwnerWorkOrder).toHaveBeenCalledWith(readyOrder.wo_id, 'approved', '')
    expect(appAlert).toHaveBeenCalledWith(
      `工单 ${readyOrder.wo_id} 已记录为 approved，操作人 owner:42`,
    )
    wrapper.unmount()
  })

  it('asks for a reason on non-approval decisions and reports refresh errors', async () => {
    fetchOwnerWorkOrders
      .mockResolvedValueOnce({ ok: true, count: 1, items: [readyOrder] })
      .mockRejectedValueOnce(new Error('service unavailable'))
    const wrapper = mount(ApprovalHubView)
    await flushPromises()

    await wrapper.find('.work-order .btn-secondary').trigger('click')
    await flushPromises()
    expect(appPrompt).toHaveBeenCalledWith('暂缓说明（可选）', '')
    expect(decideOwnerWorkOrder).toHaveBeenCalledWith(readyOrder.wo_id, 'held', '已复核证据')
    expect(wrapper.text()).toContain('工单刷新失败：service unavailable')

    wrapper.unmount()
  })
})
