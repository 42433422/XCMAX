import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import MeetingRoomView from './MeetingRoomView.vue'

describe('MeetingRoomView', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_AGORA_APP_ID', '')
  })

  function mountView() {
    return mount(MeetingRoomView)
  }

  it('renders the page header', () => {
    const wrapper = mountView()
    expect(wrapper.find('.meeting-poc-head h1').text()).toContain('音视频 PoC')
  })

  it('renders the muted description', () => {
    const wrapper = mountView()
    expect(wrapper.find('.muted').text()).toContain('P2 集成验证页')
  })

  it('renders channel, uid, token inputs', () => {
    const wrapper = mountView()
    const inputs = wrapper.findAll('input')
    expect(inputs.length).toBeGreaterThanOrEqual(3)
  })

  it('initializes channel with default value', () => {
    const wrapper = mountView()
    const channelInput = wrapper.findAll('input')[0]
    expect((channelInput.element as HTMLInputElement).value).toBe('xcagi-demo-1v1')
  })

  it('initializes uid with a numeric string', () => {
    const wrapper = mountView()
    const uidInput = wrapper.findAll('input')[1]
    const val = (uidInput.element as HTMLInputElement).value
    expect(val).toMatch(/^\d+$/)
  })

  it('shows default status "未连接"', () => {
    const wrapper = mountView()
    expect(wrapper.text()).toContain('未连接')
  })

  it('renders join and leave buttons', () => {
    const wrapper = mountView()
    const buttons = wrapper.findAll('button')
    expect(buttons.length).toBe(2)
    expect(buttons[0].text()).toBe('加入')
    expect(buttons[1].text()).toBe('离开')
  })

  it('shows error when appId is empty and join is clicked', async () => {
    const wrapper = mountView()
    await wrapper.findAll('button')[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.meeting-error').exists()).toBe(true)
    expect(wrapper.find('.meeting-error').text()).toContain('VITE_AGORA_APP_ID')
  })

  it('shows PoC ready message when appId is set and join is clicked', async () => {
    vi.stubEnv('VITE_AGORA_APP_ID', 'test-app-id')
    const wrapper = mountView()
    await wrapper.findAll('button')[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.meeting-error').text()).toContain('PoC 壳页已就绪')
    expect(wrapper.text()).toContain('待接入')
  })

  it('updates status to "已离开" when leave is clicked', async () => {
    const wrapper = mountView()
    await wrapper.findAll('button')[1].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已离开')
  })

  it('clears error message when leave is clicked', async () => {
    const wrapper = mountView()
    await wrapper.findAll('button')[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.meeting-error').exists()).toBe(true)
    await wrapper.findAll('button')[1].trigger('click')
    await flushPromises()
    expect(wrapper.find('.meeting-error').exists()).toBe(false)
  })

  it('renders local and remote video sections', () => {
    const wrapper = mountView()
    const headings = wrapper.findAll('h2')
    expect(headings.length).toBe(2)
    expect(headings[0].text()).toBe('本地')
    expect(headings[1].text()).toBe('远端')
  })

  it('renders video boxes', () => {
    const wrapper = mountView()
    expect(wrapper.findAll('.video-box')).toHaveLength(2)
  })

  it('sets document title on mount', () => {
    mountView()
    expect(document.title).toBe('会议 PoC · 声网')
  })

  it('updates channel value when input changes', async () => {
    const wrapper = mountView()
    const channelInput = wrapper.findAll('input')[0]
    await channelInput.setValue('new-channel')
    expect((channelInput.element as HTMLInputElement).value).toBe('new-channel')
  })

  it('updates uid value when input changes', async () => {
    const wrapper = mountView()
    const uidInput = wrapper.findAll('input')[1]
    await uidInput.setValue('9999')
    expect((uidInput.element as HTMLInputElement).value).toBe('9999')
  })

  it('updates token value when input changes', async () => {
    const wrapper = mountView()
    const tokenInput = wrapper.findAll('input')[2]
    await tokenInput.setValue('my-token')
    expect((tokenInput.element as HTMLInputElement).value).toBe('my-token')
  })
})
