import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const showAlert = vi.fn();
const showConfirm = vi.fn();
const showPrompt = vi.fn();

vi.mock('@/stores/appDialog', () => ({
  useAppDialogStore: () => ({
    showAlert,
    showConfirm,
    showPrompt,
  }),
}));

import { appAlert, appConfirm, appPrompt } from './appDialog';

beforeEach(() => {
  setActivePinia(createPinia());
  showAlert.mockReset();
  showConfirm.mockReset();
  showPrompt.mockReset();
});

describe('appDialog helpers', () => {
  it('appAlert delegates to store', async () => {
    showAlert.mockResolvedValue(undefined);
    await appAlert('hello', { title: 'T' });
    expect(showAlert).toHaveBeenCalledWith('hello', { title: 'T' });
  });

  it('appConfirm delegates to store', async () => {
    showConfirm.mockResolvedValue(true);
    const ok = await appConfirm('sure?');
    expect(ok).toBe(true);
    expect(showConfirm).toHaveBeenCalledWith('sure?', undefined);
  });

  it('appPrompt delegates with default value', async () => {
    showPrompt.mockResolvedValue('value');
    const out = await appPrompt('name?', 'def');
    expect(out).toBe('value');
    expect(showPrompt).toHaveBeenCalledWith('name?', 'def', undefined);
  });
});
