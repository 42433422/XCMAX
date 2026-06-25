import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import HelloWorld from './HelloWorld.vue'

describe('HelloWorld.vue', () => {
  it('renders the msg prop as heading', () => {
    const wrapper = mount(HelloWorld, { props: { msg: 'Hello XCMAX' } })
    expect(wrapper.find('h1').text()).toBe('Hello XCMAX')
  })

  it('renders default count value of 0', () => {
    const wrapper = mount(HelloWorld, { props: { msg: 'Hi' } })
    expect(wrapper.find('button').text()).toContain('count is 0')
  })

  it('increments count when button clicked', async () => {
    const wrapper = mount(HelloWorld, { props: { msg: 'Hi' } })
    const btn = wrapper.find('button')
    await btn.trigger('click')
    expect(btn.text()).toContain('count is 1')
    await btn.trigger('click')
    await btn.trigger('click')
    expect(btn.text()).toContain('count is 3')
  })

  it('renders starter template links', () => {
    const wrapper = mount(HelloWorld, { props: { msg: 'Hi' } })
    const links = wrapper.findAll('a')
    expect(links.length).toBeGreaterThanOrEqual(2)
    expect(wrapper.text()).toContain('create-vue')
    expect(wrapper.text()).toContain('Volar')
  })

  it('renders without msg prop', () => {
    const wrapper = mount(HelloWorld)
    expect(wrapper.find('h1').text()).toBe('')
    expect(wrapper.find('button').exists()).toBe(true)
  })

  it('renders read-the-docs paragraph', () => {
    const wrapper = mount(HelloWorld, { props: { msg: 'Hi' } })
    expect(wrapper.find('.read-the-docs').exists()).toBe(true)
  })
})
