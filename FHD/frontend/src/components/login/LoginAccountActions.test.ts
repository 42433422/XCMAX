import { mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>();
  return {
    ...actual,
    useRoute: () => ({ query: { redirect: '/tasks' } }),
  };
});

import LoginAccountActions from './LoginAccountActions.vue';

const mountActions = (enterprise: boolean) =>
  mount(LoginAccountActions, {
    props: { enterprise },
    global: {
      mocks: { $t: (key: string) => key },
      stubs: {
        RouterLink: {
          props: ['to'],
          template: '<a class="router-link-stub" :data-to="JSON.stringify(to)"><slot /></a>',
        },
      },
    },
  });

describe('LoginAccountActions', () => {
  it('opens the shared market registration route with desktop source for enterprise builds', () => {
    const wrapper = mountActions(true);
    const registration = wrapper.find('a.login-account-action');

    expect(registration.attributes('href')).toBe(
      'https://xiu-ci.com/market/register?source=xcagi-desktop',
    );
    expect(registration.attributes('target')).toBe('_blank');
    expect(registration.attributes('rel')).toBe('noopener noreferrer');
  });

  it('keeps the local registration route for non-enterprise builds', () => {
    const wrapper = mountActions(false);

    expect(wrapper.find('.router-link-stub').attributes('data-to')).toContain('login-register');
    expect(wrapper.find('a[href*="xiu-ci.com/market/register"]').exists()).toBe(false);
  });
});
