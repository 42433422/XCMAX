import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';
import LanGateView from './LanGateView.vue';

describe('LanGateView.vue', () => {
  it('exports a Vue component', () => {
    expect(LanGateView).toBeTruthy();
  });

  it('renders host mod bridge stub', () => {
    const wrapper = mount(LanGateView, {
      global: {
        stubs: {
          HostModBridgeView: {
            template: '<div class="host-mod-bridge-stub" />',
          },
        },
      },
    });
    expect(wrapper.find('.host-mod-bridge-stub').exists()).toBe(true);
  });
});
