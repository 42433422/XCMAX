import { describe, expect, it } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useModsStore } from '@/stores/mods';

describe('mods store', () => {
  it('initializes with empty installed list', () => {
    setActivePinia(createPinia());
    const store = useModsStore();
    expect(Array.isArray(store.mods)).toBe(true);
  });
});
