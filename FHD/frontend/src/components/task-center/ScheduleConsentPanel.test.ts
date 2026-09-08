import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import ScheduleConsentPanel from './ScheduleConsentPanel.vue'

const api = vi.hoisted(() => ({ inspectScheduleConsent: vi.fn(), authorizeSchedule: vi.fn(), revokeScheduleConsent: vi.fn() }))
vi.mock('@/api/agentRuns', () => ({ default: api }))
const scope = { scope_hash: 'reviewed-scope', operation: { tool_id: 'products', action: 'query', params: { keyword: 'sample' } }, authorization: null }

describe('bounded schedule consent', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.inspectScheduleConsent.mockResolvedValue({ success: true, data: scope })
  })

  it('requires scope review and explicit confirmation before granting', async () => {
    const wrapper = mount(ScheduleConsentPanel, { props: { scheduleId: 'schedule-1' } })
    expect(api.authorizeSchedule).not.toHaveBeenCalled()
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('sample')
    const grantButton = wrapper.findAll('button').find(button => button.text() === '确认授权自动执行')!
    expect(grantButton.attributes('disabled')).toBeDefined()
    await wrapper.find('input[type="datetime-local"]').setValue('2030-01-01T08:00')
    await wrapper.find('input[type="number"]').setValue('5')
    await wrapper.find('input[type="checkbox"]').setValue(true)
    api.authorizeSchedule.mockResolvedValue({ success: true })
    await grantButton.trigger('click')
    await flushPromises()
    expect(api.authorizeSchedule).toHaveBeenCalledWith('schedule-1', {
      scope_hash: 'reviewed-scope', max_runs: 5, expires_at: new Date('2030-01-01T08:00').toISOString(),
    })
    wrapper.unmount()
  })

  it('discards old account scope and cannot authorize it', async () => {
    let resolveOld!: (value: unknown) => void
    api.inspectScheduleConsent.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve }))
    const wrapper = mount(ScheduleConsentPanel, { props: { scheduleId: 'schedule-1' } })
    await wrapper.find('button').trigger('click')
    productReadAccountEpoch.value++
    resolveOld({ success: true, data: scope })
    await flushPromises()
    expect(wrapper.find('section').exists()).toBe(false)
    expect(api.authorizeSchedule).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
