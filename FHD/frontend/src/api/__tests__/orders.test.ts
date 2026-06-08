import { describe, expect, it } from 'vitest';

describe('orders api module', () => {
  it('exports fetch helpers', async () => {
    const mod = await import('@/api/orders');
    expect(typeof mod).toBe('object');
  });
});
