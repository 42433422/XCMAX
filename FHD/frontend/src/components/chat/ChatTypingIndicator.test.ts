import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatTypingIndicator from './ChatTypingIndicator.vue'

describe('ChatTypingIndicator', () => {
  it('renders the indicator container with role=status', () => {
    const wrapper = mount(ChatTypingIndicator)
    expect(wrapper.find('.chat-typing-indicator').exists()).toBe(true)
    expect(wrapper.find('.chat-typing-indicator').attributes('role')).toBe('status')
  })

  it('renders three dots', () => {
    const wrapper = mount(ChatTypingIndicator)
    expect(wrapper.findAll('.chat-typing-indicator__dot')).toHaveLength(3)
  })

  it('uses default aria-label when no label prop', () => {
    const wrapper = mount(ChatTypingIndicator)
    expect(wrapper.find('.chat-typing-indicator').attributes('aria-label')).toBe('正在输入')
  })

  it('uses provided label as aria-label', () => {
    const wrapper = mount(ChatTypingIndicator, { props: { label: 'AI 思考中' } })
    expect(wrapper.find('.chat-typing-indicator').attributes('aria-label')).toBe('AI 思考中')
  })

  it('does not render label span when label prop is absent', () => {
    const wrapper = mount(ChatTypingIndicator)
    expect(wrapper.find('.chat-typing-indicator__label').exists()).toBe(false)
  })

  it('renders label span when label prop is provided', () => {
    const wrapper = mount(ChatTypingIndicator, { props: { label: '正在分析' } })
    expect(wrapper.find('.chat-typing-indicator__label').exists()).toBe(true)
    expect(wrapper.find('.chat-typing-indicator__label').text()).toBe('正在分析')
  })

  it('applies staggered animation delays to dots', () => {
    const wrapper = mount(ChatTypingIndicator)
    const dots = wrapper.findAll('.chat-typing-indicator__dot')
    expect(dots[0].attributes('style')).toContain('animation-delay: 0s')
    expect(dots[1].attributes('style')).toContain('animation-delay: 0.16s')
    expect(dots[2].attributes('style')).toContain('animation-delay: 0.32s')
  })

  it('has aria-live=polite for accessibility', () => {
    const wrapper = mount(ChatTypingIndicator)
    expect(wrapper.find('.chat-typing-indicator').attributes('aria-live')).toBe('polite')
  })
})
