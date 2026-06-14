import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useAccountProfileStore } from '@/stores/accountProfile';
import { useModsStore } from '@/stores/mods';
import { useWorkflowPanoramaNavVisible } from './useWorkflowPanoramaNavVisible';

beforeEach(() => {
  setActivePinia(createPinia());
});

describe('useWorkflowPanoramaNavVisible', () => {
  it('hides panorama for enterprise ERP sidebar context', () => {
    const account = useAccountProfileStore();
    account.$patch({
      accountKind: 'enterprise',
      marketIsAdmin: false,
      marketIsEnterprise: true,
    });
    const mods = useModsStore();
    mods.$patch({
      activeModId: 'erp',
      mods: [{ id: 'erp' }],
    });
    const { showWorkflowPanoramaNav } = useWorkflowPanoramaNavVisible();
    expect(showWorkflowPanoramaNav.value).toBe(false);
  });

  it('shows panorama for admin account', () => {
    const account = useAccountProfileStore();
    account.$patch({
      accountKind: 'admin',
      marketIsAdmin: true,
      marketIsEnterprise: false,
    });
    const mods = useModsStore();
    mods.$patch({ activeModId: '', mods: [] });
    const { showWorkflowPanoramaNav } = useWorkflowPanoramaNavVisible();
    expect(showWorkflowPanoramaNav.value).toBe(true);
  });
});
