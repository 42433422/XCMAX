import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LoginAccountActions from './LoginAccountActions.vue'

describe('LoginAccountActions', () => {
  it('renders a single shared market registration link', () => {
    const wrapper = mount(LoginAccountActions)
    const links = wrapper.findAll('a')
    expect(links).toHaveLength(1)
    expect(links[0].attributes('href')).toBe('https://xiu-ci.com/market/register?source=xcagi-desktop')
    expect(links[0].attributes('target')).toBe('_blank')
    expect(links[0].attributes('rel')).toBe('noopener noreferrer')
  })
})
