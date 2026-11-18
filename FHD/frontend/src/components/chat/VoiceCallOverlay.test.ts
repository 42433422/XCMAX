import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import VoiceCallOverlay from './VoiceCallOverlay.vue'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => wrappers.splice(0).forEach(w => w.unmount()))
function render() {
  const wrapper = mount(VoiceCallOverlay, { props: { stage: 'listening', durationText: '01:23', statusText: '正在聆听' }, global: { stubs: { teleport: true } } })
  wrappers.push(wrapper)
  return wrapper
}

describe('VoiceCallOverlay presentation and controls', () => {
  it('shows current call status, transcript and hides stale errors after hangup', async () => {
    const wrapper = render()
    expect(wrapper.get('[role="dialog"]').attributes('aria-label')).toBe('语音通话')
    expect(wrapper.get('.voice-call-name').text()).toBe('通用助手')
    expect(wrapper.get('.voice-call-duration').text()).toBe('01:23')
    expect(wrapper.get('.voice-call-status').text()).toBe('正在聆听')
    expect(wrapper.find('.voice-call-spinner').exists()).toBe(true)
    expect(wrapper.find('.voice-call-line').exists()).toBe(false)
    await wrapper.setProps({ title: '订单助手', heardText: '查询订单', replyText: '正在查询', errorText: '连接中断' })
    expect(wrapper.findAll('.voice-call-line-label').map(x => x.text())).toEqual(['你', '订单助手'])
    expect(wrapper.findAll('.voice-call-line-text').map(x => x.text())).toEqual(['查询订单', '正在查询'])
    expect(wrapper.get('.voice-call-error').text()).toBe('连接中断')
    await wrapper.setProps({ stage: 'ended', statusText: '通话结束' })
    expect(wrapper.find('.voice-call-spinner').exists()).toBe(false)
    expect(wrapper.find('.voice-call-error').exists()).toBe(false)
    expect(wrapper.get('.voice-call-status').text()).toBe('通话结束')
  })

  it('emits separate mute, speaker and hangup actions and reflects parent-controlled state', async () => {
    const wrapper = render()
    let controls = wrapper.findAll('.voice-call-controls button')
    await controls[0].trigger('click')
    await controls[2].trigger('click')
    expect(wrapper.emitted('toggle-mute')).toHaveLength(1)
    expect(wrapper.emitted('toggle-speaker')).toHaveLength(1)
    await wrapper.setProps({ muted: true, speakerOn: false })
    controls = wrapper.findAll('.voice-call-controls button')
    expect(controls[0].classes()).toContain('active')
    expect(controls[0].text()).toBe('取消静音')
    expect(controls[0].find('.fa-microphone-slash').exists()).toBe(true)
    expect(controls[2].classes()).not.toContain('active')
    expect(controls[2].find('.fa-volume-off').exists()).toBe(true)
    await controls[1].trigger('click')
    await wrapper.get('.voice-call-collapse').trigger('click')
    expect(wrapper.emitted('hangup')).toHaveLength(2)
  })
})
