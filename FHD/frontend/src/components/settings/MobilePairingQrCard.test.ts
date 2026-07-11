import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';

import MobilePairingQrCard from './MobilePairingQrCard.vue';

const mocks = vi.hoisted(() => ({
  issue: vi.fn(),
  desktop: vi.fn(),
  qr: vi.fn(),
}));

vi.mock('qrcode', () => ({
  default: { toDataURL: mocks.qr },
}));

vi.mock('@/api/mobilePairing', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/mobilePairing')>();
  return {
    ...actual,
    fetchHostDiscoverHint: vi.fn(async () => ({ api_port: 17500 })),
    loadDesktopPairingPayload: mocks.desktop,
    issueMobilePairing: mocks.issue,
    resolvePairingHost: vi.fn(() => '192.168.10.2'),
    resolveReachablePairingPort: vi.fn(() => 17500),
  };
});

describe('MobilePairingQrCard', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it('keeps enterprise default and issues management QR only after explicit switch', async () => {
    vi.useFakeTimers();
    mocks.desktop.mockResolvedValue(null);
    mocks.issue.mockImplementation(async (_host, _port, purpose) => ({
      host: '192.168.10.2',
      port: 17500,
      nonce: `nonce-${purpose}`,
      shortCode: purpose === 'management' ? '654321' : '123456',
      exp: Math.floor(Date.now() / 1000) + 120,
    }));
    mocks.qr.mockResolvedValue('data:image/png;base64,qr');

    const wrapper = mount(MobilePairingQrCard, {
      props: { allowManagement: true },
    });
    await flushPromises();

    expect(mocks.desktop).toHaveBeenLastCalledWith('enterprise');
    expect(mocks.issue).toHaveBeenLastCalledWith(
      '192.168.10.2',
      17500,
      'enterprise',
    );
    expect(wrapper.text()).toContain('123456');
    expect(wrapper.text()).not.toContain('员工决策、验收、停止和改派');

    const modeButtons = wrapper.findAll('.mobile-pairing__mode-button');
    await modeButtons[1].trigger('click');
    await flushPromises();

    expect(mocks.desktop).toHaveBeenLastCalledWith('management');
    expect(mocks.issue).toHaveBeenLastCalledWith(
      '192.168.10.2',
      17500,
      'management',
    );
    expect(wrapper.text()).toContain('654321');
    expect(wrapper.text()).toContain('员工决策、验收、停止和改派');

    wrapper.unmount();
  });

  it('keeps management controls hidden and only requests enterprise pairing by default', async () => {
    vi.useFakeTimers();
    mocks.desktop.mockResolvedValue(null);
    mocks.issue.mockResolvedValue({
      host: '192.168.10.2',
      port: 17500,
      nonce: 'nonce-enterprise',
      shortCode: '123456',
      exp: Math.floor(Date.now() / 1000) + 120,
    });
    mocks.qr.mockResolvedValue('data:image/png;base64,qr');

    const wrapper = mount(MobilePairingQrCard);
    await flushPromises();

    expect(wrapper.find('.mobile-pairing__mode').exists()).toBe(false);
    expect(wrapper.find('.mobile-pairing__management-warning').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('管理端手机');
    expect(wrapper.text()).not.toContain('员工决策、验收、停止和改派');
    expect(wrapper.text()).toContain('123456');
    expect(mocks.desktop.mock.calls.every(([purpose]) => purpose === 'enterprise')).toBe(true);
    expect(mocks.issue.mock.calls.every(([, , purpose]) => purpose === 'enterprise')).toBe(true);

    wrapper.unmount();
  });
});
