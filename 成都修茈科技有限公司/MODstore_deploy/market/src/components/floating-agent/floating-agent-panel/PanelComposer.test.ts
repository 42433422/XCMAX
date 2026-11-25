import { shallowMount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PanelComposer from './PanelComposer.vue'

vi.mock('../../../stores/agent', () => ({
  useAgentStore: () => ({ isLoading: false }),
}))

describe.each([true, false])('PanelComposer corpMode=%s', (corpMode) => {
  it('has a single voice, attachment, input and send control in either layout', async () => {
    const wrapper = shallowMount(PanelComposer, {
      props: {
        corpMode, isLightTheme: true, draft: '保存草稿', hasPendingImage: false,
        imagePicking: false, voiceState: 'idle', isSupported: false, error: '',
      },
      slots: { autonomy: '<button data-testid="autonomy-slot">自主任务</button>' },
    })
    try {
      expect(wrapper.findAll('agent-voice-input-stub')).toHaveLength(1)
      expect(wrapper.findAll('.panel-shot-btn')).toHaveLength(1)
      expect(wrapper.findAll('textarea')).toHaveLength(1)
      expect(wrapper.findAll('.panel-send')).toHaveLength(1)
      expect(wrapper.find('.panel-composer-layout--corp').exists()).toBe(corpMode)
      expect(wrapper.find('[data-testid="autonomy-slot"]').exists()).toBe(!corpMode)
      expect(wrapper.get('textarea').attributes('value')).toBe('保存草稿')
    } finally {
      wrapper.unmount()
    }
  })

  it('does not submit IME confirmation, Shift+Enter or an empty draft', async () => {
    const wrapper = shallowMount(PanelComposer, {
      props: {
        corpMode, isLightTheme: true, draft: '', hasPendingImage: false,
        imagePicking: false, voiceState: 'idle', isSupported: false, error: '',
      },
    })
    try {
      const input = wrapper.get('textarea')
      const dispatch = (init: KeyboardEventInit = {}) => {
        const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true, ...init })
        input.element.dispatchEvent(event)
        return event
      }
      dispatch()
      expect(wrapper.emitted('send')).toBeUndefined()
      await wrapper.setProps({ draft: '中文草稿' })
      for (const init of [{ isComposing: true }, { keyCode: 229 }, { shiftKey: true }]) {
        expect(dispatch(init).defaultPrevented).toBe(false)
      }
      expect(wrapper.emitted('send')).toBeUndefined()
      expect(dispatch().defaultPrevented).toBe(true)
      expect(wrapper.emitted('send')).toHaveLength(1)
      await wrapper.setProps({ imagePicking: true })
      dispatch()
      expect(wrapper.emitted('send')).toHaveLength(1)
    } finally {
      wrapper.unmount()
    }
  })
})
