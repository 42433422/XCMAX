import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import JarvisMonitorFloatWrap from './JarvisMonitorFloatWrap.vue'

const sampleContacts = [
  { id: '1', name: '张三', unreadCount: 0 },
  { id: '2', name: '李四', unreadCount: 3 },
  { id: '3', name: '', unreadCount: 0 },
]

describe('JarvisMonitorFloatWrap', () => {
  it('renders the wrap container', () => {
    const wrapper = mount(JarvisMonitorFloatWrap, { props: { contacts: [] } })
    expect(wrapper.find('.jarvis-monitor-float-wrap').exists()).toBe(true)
  })

  it('does not apply task-acquiring class by default', () => {
    const wrapper = mount(JarvisMonitorFloatWrap, { props: { contacts: [] } })
    expect(wrapper.find('.jarvis-monitor-float-wrap').classes()).not.toContain('task-acquiring')
  })

  it('applies task-acquiring class when isTaskAcquiring is true', () => {
    const wrapper = mount(JarvisMonitorFloatWrap, {
      props: { contacts: [], isTaskAcquiring: true },
    })
    expect(wrapper.find('.jarvis-monitor-float-wrap').classes()).toContain('task-acquiring')
  })

  it('renders no contacts when contacts prop is empty', () => {
    const wrapper = mount(JarvisMonitorFloatWrap, { props: { contacts: [] } })
    expect(wrapper.findAll('.monitor-float-contact')).toHaveLength(0)
  })

  it('renders all provided contacts', () => {
    const wrapper = mount(JarvisMonitorFloatWrap, { props: { contacts: sampleContacts } })
    expect(wrapper.findAll('.monitor-float-contact')).toHaveLength(3)
  })

  it('renders first character of contact name as avatar', () => {
    const wrapper = mount(JarvisMonitorFloatWrap, { props: { contacts: sampleContacts } })
    const avatars = wrapper.findAll('.float-avatar')
    expect(avatars[0].text()).toBe('张')
    expect(avatars[1].text()).toBe('李')
  })

  it('renders "?" as avatar when name is empty', () => {
    const wrapper = mount(JarvisMonitorFloatWrap, { props: { contacts: sampleContacts } })
    const avatars = wrapper.findAll('.float-avatar')
    expect(avatars[2].text()).toBe('?')
  })

  it('renders contact name', () => {
    const wrapper = mount(JarvisMonitorFloatWrap, { props: { contacts: sampleContacts } })
    const names = wrapper.findAll('.float-name')
    expect(names[0].text()).toBe('张三')
    expect(names[1].text()).toBe('李四')
  })

  it('marks avatar as unread when unreadCount > 0', () => {
    const wrapper = mount(JarvisMonitorFloatWrap, { props: { contacts: sampleContacts } })
    const avatars = wrapper.findAll('.float-avatar')
    expect(avatars[1].classes()).toContain('unread')
    expect(avatars[0].classes()).not.toContain('unread')
  })

  it('applies transform style based on radius and index', () => {
    const wrapper = mount(JarvisMonitorFloatWrap, {
      props: { contacts: sampleContacts, radius: 200 },
    })
    const contacts = wrapper.findAll('.monitor-float-contact')
    expect(contacts[0].attributes('style')).toContain('translate')
    expect(contacts[0].attributes('style')).toContain('200px')
  })

  it('applies staggered animation delay based on index', () => {
    const wrapper = mount(JarvisMonitorFloatWrap, { props: { contacts: sampleContacts } })
    const contacts = wrapper.findAll('.monitor-float-contact')
    expect(contacts[0].attributes('style')).toContain('animation-delay: 0s')
    expect(contacts[1].attributes('style')).toContain('animation-delay: 0.1s')
    expect(contacts[2].attributes('style')).toContain('animation-delay: 0.2s')
  })
})
