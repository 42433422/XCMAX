import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import LoginView from './LoginView.vue'

describe('LoginView.vue', () => {
  it('exports a Vue component', () => {
    expect(LoginView).toBeTruthy()
  })

  it('renders login form shell', () => {
    const wrapper = mount(LoginView, {
      global: {
        stubs: { RouterLink: true, RouterView: true },
      },
    })
    expect(wrapper.text().length).toBeGreaterThan(0)
  })
})
