import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Panel from '../../../admin-console/src/components/admin/MaintenanceExecutionPanel.vue'
import api from '@/api/core'
vi.mock('@/api/core', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/utils/appDialog', () => ({ appConfirm: vi.fn(async () => true) }))
const snapshot = { ok: true, connected: true, environment: '隔离验收', tasks: [{ action: 'restart_service', label: '重启服务' }], executions: [{ id: '1', label: '重启服务', action: 'restart_service', status: 'running', recovery: 'unverified' }], pending: [] }
beforeEach(() => { vi.clearAllMocks(); vi.useFakeTimers(); vi.mocked(api.get).mockResolvedValue(snapshot); vi.mocked(api.post).mockResolvedValue({ ok: true, state: 'cancel_requested' }) })
afterEach(() => vi.useRealTimers())
it('shows real states and cancels through the existing admin API', async () => {
 const wrapper = mount(Panel); await flushPromises()
 expect(wrapper.text()).toContain('隔离验收'); expect(wrapper.text()).toContain('尚未核实')
 await wrapper.findAll('button').find(b => b.text() === '取消任务')!.trigger('click'); await flushPromises()
 expect(api.post).toHaveBeenCalledWith('/api/xcmax/admin/autonomy/maintenance/1/cancel', {})
 expect(wrapper.text()).toContain('最终状态以任务记录为准'); wrapper.unmount()
})
it('clears old task data and disables execution when connection fails', async () => {
 const wrapper = mount(Panel); await flushPromises()
 vi.mocked(api.get).mockRejectedValueOnce(new Error('offline'))
 await wrapper.findAll('button').find(b => b.text() === '刷新状态')!.trigger('click'); await flushPromises()
 expect(wrapper.text()).toContain('offline'); expect(wrapper.text()).not.toContain('编号 1')
 expect(wrapper.findAll('button').some(b => b.text() === '申请重启服务')).toBe(false); wrapper.unmount()
})
it('keeps cancellation available during a running request', async () => {
 const wrapper = mount(Panel); await flushPromises()
 vi.mocked(api.post).mockReturnValueOnce(new Promise(() => {}))
 await wrapper.findAll('button').find(b => b.text() === '申请重启服务')!.trigger('click'); await flushPromises()
 expect(wrapper.findAll('button').find(b => b.text() === '取消任务')!.attributes('disabled')).toBeUndefined(); wrapper.unmount()
})
