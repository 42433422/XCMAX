import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';
import { createRouter, createMemoryHistory } from 'vue-router';
import RegisterView from './RegisterView.vue';

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/register', name: 'register', component: RegisterView }],
  });
}

describe('RegisterView.vue', () => {
  it('exports a Vue component', () => {
    expect(RegisterView).toBeTruthy();
  });

  it('renders registration shell', async () => {
    const router = makeRouter();
    await router.push('/register');
    await router.isReady();
    const wrapper = mount(RegisterView, {
      global: {
        plugins: [router],
        stubs: { RouterLink: true, RouterView: true },
      },
    });
    expect(wrapper.text().length).toBeGreaterThan(0);
  });
});
