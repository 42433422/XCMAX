import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import KellaiView from '../../../mods/tools/kellai/frontend/views/KellaiView.vue'
import KellaiMessageComposer from '@/components/im/kellaiInbox/KellaiMessageComposer.vue'
import { deliveryTargetKey, useKellaiStore } from '@/stores/kellai'

const api = vi.hoisted(() => ({ status: vi.fn(), start: vi.fn(), dataStatus: vi.fn(), customers: vi.fn(), channels: vi.fn(), conversations: vi.fn(), latestDraft: vi.fn(), followUpOverview: vi.fn(), sendReceipt: vi.fn(), sendMessage: vi.fn() }))
vi.mock('@/api/kellaiBinding', () => ({ default: api }))
vi.mock('@/components/LocalFileAccessCard.vue', () => ({ default: { template: '<div>本机文件授权</div>' } }))

describe('Kellai product module', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.status.mockResolvedValue({ state: 'not_connected' })
    api.start.mockResolvedValue({ request_id: 'pending-request' })
    ;(window as Window & { xcagiDesktop?: unknown }).xcagiDesktop = { openKellaiDesktop: vi.fn().mockResolvedValue({ ok: true }) }
  })
  afterEach(() => { delete (window as Window & { xcagiDesktop?: unknown }).xcagiDesktop })

  it('shows the five workspaces and requests send permission only after explicit selection', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/kellai', component: KellaiView }] })
    await router.push('/kellai')
    await router.isReady()
    const wrapper = mount(KellaiView, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.findAll('h1').map(item => item.text())).toEqual(['智能生态 / 客来来'])
    expect(wrapper.findAll('[role="tab"]').map(item => item.text())).toEqual(['连接与账号', '消息中心', '联系人', '数据接入', '自动化'])
    const authorize = () => wrapper.findAll('button').find(item => item.text() === '连接客来来')!
    await authorize().trigger('click')
    await flushPromises()
    expect(api.start).toHaveBeenLastCalledWith(['customer_profiles.read', 'customer_conversations.read', 'channels.read'])
    await wrapper.get('.el-switch').trigger('click')
    await authorize().trigger('click')
    await flushPromises()
    expect(api.start).toHaveBeenLastCalledWith(['customer_profiles.read', 'customer_conversations.read', 'channels.read', 'messages.send'])
    wrapper.unmount()
  })

  it('keeps receipt recovery available when the original channel is offline', async () => {
    const store = useKellaiStore()
    store.binding = { state: 'connected', connection: { connection_id: 'paired', authorized_scopes: ['messages.send'] } }
    store.activeCustomerId = 7
    const key = deliveryTargetKey({ customer_id: 7, channel_type: 'chatwoot', contact_id: 'conversation-9' })
    store.deliveries[key] = { request_id: 'existing-request-id', receipt: { request_id: 'existing-request-id', status: 'unknown' }, checking: false, error: '' }
    api.sendReceipt.mockResolvedValue({ request_id: 'existing-request-id', status: 'accepted', persisted: false })
    const wrapper = mount(KellaiMessageComposer)
    expect(wrapper.text()).toContain('当前会话没有已连接且支持发送的联系人')
    expect(wrapper.text()).toContain('发送结果未知')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(api.sendReceipt).toHaveBeenCalledExactlyOnceWith('existing-request-id')
    expect(api.sendMessage).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('尚无送达确认')
    expect(wrapper.text()).toContain('发送记录尚未同步到会话')
    wrapper.unmount()
  })
})
