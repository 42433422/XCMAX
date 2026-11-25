import { shallowMount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PanelComposer from './PanelComposer.vue'

vi.mock('../../../stores/agent', () => ({
  useAgentStore: () => ({ isLoading: false }),
}))

describe.each([true, false])('PanelComposer corpMode=%s', (corpMode) => {
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
