import { test, expect } from '@playwright/test';
import {
  installE2eShellMocks,
  csrfHeaders,
  captureEvidence,
  E2E_USER,
  E2E_PASSWORD,
  isFullStack,
} from './helpers';

test.describe('P0 critical paths', () => {
  test.beforeEach(async ({ page }) => {
    if (!isFullStack()) {
      await installE2eShellMocks(page);
    }
  });

  test('01 login — credentials establish session', async ({ page, request }) => {
    const headers = await csrfHeaders(request);
    const loginResp = await request.post('/api/auth/login', {
      headers,
      data: {
        username: E2E_USER,
        password: E2E_PASSWORD,
        account_kind: 'personal',
      },
      timeout: 20_000,
    });
    expect(loginResp.status(), await loginResp.text()).toBeLessThan(500);
    const body = await loginResp.json().catch(() => ({}));
    const accepted = loginResp.ok() || body?.success === true;
    expect(accepted, `login response: ${JSON.stringify(body)}`).toBeTruthy();

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('#app')).toBeVisible();
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    await captureEvidence(page, '01-login.png');
  });

  test('02 order — orders list API reachable', async ({ page, request }) => {
    const resp = await request.get('/api/orders', { timeout: 20_000 });
    expect(resp.status(), await resp.text()).toBeLessThan(500);

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    const orderNav = page.getByRole('button', { name: /订单|发货单|创建订单/ }).first();
    if (await orderNav.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await orderNav.click();
    }
    await captureEvidence(page, '02-order.png');
  });

  test('03 shipment — shipment list API reachable', async ({ page, request }) => {
    const resp = await request.get('/api/shipment/list', { timeout: 20_000 });
    expect(resp.status(), await resp.text()).toBeLessThan(500);

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    await captureEvidence(page, '03-shipment.png');
  });

  test('04 OCR — ocr test endpoint reachable', async ({ page, request }) => {
    const resp = await request.get('/api/ocr/test', { timeout: 20_000 });
    expect(resp.status(), await resp.text()).toBeLessThan(500);

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    await captureEvidence(page, '04-ocr.png');
  });

  test('05 mod — mods list API reachable', async ({ page, request }) => {
    const resp = await request.get('/api/mods/', { timeout: 20_000 });
    expect(resp.status(), await resp.text()).toBeLessThan(500);

    await page.goto('/ai-ecosystem', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    await captureEvidence(page, '05-mod.png');
  });
});
