import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import LoginView from './LoginView.vue'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/login', name: 'login', component: LoginView }],
  })
}

describe('LoginView.vue', () => {
  it('exports a Vue component', () => {
    expect(LoginView).toBeTruthy()
  })

  it('renders login form shell', async () => {
    const router = makeRouter()
    await router.push('/login')
    await router.isReady()
    const wrapper = mount(LoginView, {
      global: {
        plugins: [router],
        stubs: { RouterLink: true, RouterView: true },
      },
    })
    expect(wrapper.text().length).toBeGreaterThan(0)
  })
})
