import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useAppDialogStore } from './appDialog';

beforeEach(() => {
  setActivePinia(createPinia());
});

describe('appDialog store — alert', () => {
  it('opens alert with defaults and resolves on ack', async () => {
    const s = useAppDialogStore();
    const p = s.showAlert('hello');
    expect(s.visible).toBe(true);
    expect(s.kind).toBe('alert');
    expect(s.title).toBe('提示');
    expect(s.message).toBe('hello');
    s.ackAlert();
    await expect(p).resolves.toBeUndefined();
    expect(s.visible).toBe(false);
  });

  it('respects custom title (trimmed)', async () => {
    const s = useAppDialogStore();
    const p = s.showAlert('m', { title: '  自定义  ' });
    expect(s.title).toBe('自定义');
    s.ackAlert();
    await p;
  });
});

describe('appDialog store — confirm', () => {
  it('resolves true when confirmed', async () => {
    const s = useAppDialogStore();
    const p = s.showConfirm('ok?');
    expect(s.kind).toBe('confirm');
    expect(s.title).toBe('确认');
    s.ackConfirm(true);
    await expect(p).resolves.toBe(true);
  });

  it('resolves false when cancelled', async () => {
    const s = useAppDialogStore();
    const p = s.showConfirm('ok?', { danger: true, confirmText: '删', cancelText: '不' });
    expect(s.danger).toBe(true);
    expect(s.confirmText).toBe('删');
    expect(s.cancelText).toBe('不');
    s.ackConfirm(false);
    await expect(p).resolves.toBe(false);
  });
});

describe('appDialog store — prompt', () => {
  it('resolves input value on submit', async () => {
    const s = useAppDialogStore();
    const p = s.showPrompt('name?', 'def', { placeholder: 'ph' });
    expect(s.kind).toBe('prompt');
    expect(s.promptInput).toBe('def');
    expect(s.promptPlaceholder).toBe('ph');
    s.promptInput = 'typed';
    s.ackPrompt(true);
    await expect(p).resolves.toBe('typed');
  });

  it('resolves null on cancel', async () => {
    const s = useAppDialogStore();
    const p = s.showPrompt('name?');
    s.ackPrompt(false);
    await expect(p).resolves.toBeNull();
  });
});

describe('appDialog store — queue', () => {
  it('queues second dialog until first finishes', async () => {
    const s = useAppDialogStore();
    const p1 = s.showAlert('first');
    const p2 = s.showConfirm('second');
    expect(s.message).toBe('first');
    s.ackAlert();
    await p1;
    expect(s.visible).toBe(true);
    expect(s.message).toBe('second');
    expect(s.kind).toBe('confirm');
    s.ackConfirm(true);
    await expect(p2).resolves.toBe(true);
  });
});
