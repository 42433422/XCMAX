import { test, expect } from '@playwright/test';
import { csrfHeaders, E2E_USER, E2E_PASSWORD } from './helpers';

const skipUnlessFullStack = !process.env.E2E_FULL_STACK;

test.describe('plan2026 skeleton paths (full-stack only)', () => {
  test.skip(skipUnlessFullStack, 'requires E2E_FULL_STACK=1');

  test('skeleton login', async ({ request }) => {
    const headers = await csrfHeaders(request);
    const resp = await request.post('/api/auth/login', {
      headers,
      data: { username: E2E_USER, password: E2E_PASSWORD, account_kind: 'personal' },
    });
    expect(resp.status()).toBeLessThan(500);
  });

  test('skeleton order', async ({ request }) => {
    const resp = await request.get('/api/orders');
    expect(resp.status()).toBeLessThan(500);
  });

  test('skeleton shipment', async ({ request }) => {
    const resp = await request.get('/api/shipment/list');
    expect(resp.status()).toBeLessThan(500);
  });

  test('skeleton ocr', async ({ request }) => {
    const resp = await request.get('/api/ocr/test');
    expect(resp.status()).toBeLessThan(500);
  });

  test('skeleton mod', async ({ request }) => {
    const resp = await request.get('/api/mods/');
    expect(resp.status()).toBeLessThan(500);
  });
});
