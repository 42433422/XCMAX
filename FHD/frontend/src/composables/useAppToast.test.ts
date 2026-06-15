import { describe, expect, it, vi } from 'vitest';

const message = vi.fn();
const notification = vi.fn();

vi.mock('element-plus', () => ({
  ElMessage: (opts: unknown) => message(opts),
  ElNotification: (opts: unknown) => notification(opts),
}));

import { showAppNotification, showAppToast, useAppToast } from './useAppToast';

describe('useAppToast', () => {
  it('showAppToast forwards trimmed message and level', () => {
    showAppToast('  hello  ', 'success', { duration: 1000 });
    expect(message).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'hello', type: 'success', duration: 1000 }),
    );
  });

  it('showAppToast uses blank placeholder for empty message', () => {
    showAppToast('', 'error');
    expect(message).toHaveBeenCalledWith(expect.objectContaining({ message: ' ' }));
  });

  it('showAppNotification sets title and body', () => {
    showAppNotification('标题', '正文');
    expect(notification).toHaveBeenCalledWith(
      expect.objectContaining({ title: '标题', message: '正文', duration: 4500 }),
    );
  });

  it('useAppToast returns helpers', () => {
    const api = useAppToast();
    expect(api.showAppToast).toBe(showAppToast);
    expect(api.showAppNotification).toBe(showAppNotification);
  });
});
