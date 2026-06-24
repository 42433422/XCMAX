import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageCollapseLink from './MessageCollapseLink.vue'

describe('MessageCollapseLink.vue', () => {
  it('renders a button with default label', () => {
    const wrapper = mount(MessageCollapseLink)
    expect(wrapper.find('button').exists()).toBe(true)
    expect(wrapper.text()).toContain('收起')
  })

  it('renders custom label when provided', () => {
    const wrapper = mount(MessageCollapseLink, { props: { label: '折叠内容' } })
    expect(wrapper.text()).toContain('折叠内容')
    expect(wrapper.text()).not.toContain('收起')
  })

  it('renders the chevron svg icon', () => {
    const wrapper = mount(MessageCollapseLink)
    expect(wrapper.find('svg.msg-fold__chevron').exists()).toBe(true)
  })

  it('emits collapse event when clicked', async () => {
    const wrapper = mount(MessageCollapseLink)
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('collapse')).toBeTruthy()
    expect(wrapper.emitted('collapse')).toHaveLength(1)
  })

  it('emits collapse with no payload', async () => {
    const wrapper = mount(MessageCollapseLink, { props: { label: 'Up' } })
    await wrapper.find('button').trigger('click')
    const events = wrapper.emitted('collapse')
    expect(events).toBeTruthy()
    expect(events![0]).toEqual([])
  })

  it('applies the collapse action class', () => {
    const wrapper = mount(MessageCollapseLink)
    expect(wrapper.find('.msg-fold__action--collapse').exists()).toBe(true)
  })

  it('is a button element with type=button', () => {
    const wrapper = mount(MessageCollapseLink)
    const btn = wrapper.find('button')
    expect(btn.attributes('type')).toBe('button')
  })
})
