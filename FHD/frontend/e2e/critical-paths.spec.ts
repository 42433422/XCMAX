import { test, expect } from '@playwright/test';
import {
  installE2eShellMocks,
  captureEvidence,
  isFullStack,
  loginBrowserSession,
} from './helpers';

test.describe('P0 critical paths', () => {
  test.beforeEach(async ({ page }) => {
    if (!isFullStack()) {
      await installE2eShellMocks(page);
    } else {
      await loginBrowserSession(page);
    }
  });

  test('01 login — credentials establish session', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('#app')).toBeVisible();
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    await captureEvidence(page, '01-login.png');
  });

  test('02 order — orders list API reachable', async ({ page, request }) => {
    if (isFullStack()) {
      const resp = await request.get('/api/orders', { timeout: 20_000 });
      expect(resp.status(), await resp.text()).toBeLessThan(500);
    }

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    const orderNav = page.getByRole('button', { name: /订单|发货单|创建订单/ }).first();
    if (await orderNav.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await orderNav.click();
    }
    await captureEvidence(page, '02-order.png');
  });

  test('03 shipment — shipment list API reachable', async ({ page, request }) => {
    if (isFullStack()) {
      const resp = await request.get('/api/shipment/list', { timeout: 20_000 });
      expect(resp.status(), await resp.text()).toBeLessThan(500);
    }

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    await captureEvidence(page, '03-shipment.png');
  });

  test('04 OCR — ocr test endpoint reachable', async ({ page, request }) => {
    if (isFullStack()) {
      const resp = await request.get('/api/ocr/test', { timeout: 20_000 });
      expect(resp.status(), await resp.text()).toBeLessThan(500);
    }

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    await captureEvidence(page, '04-ocr.png');
  });

  test('05 mod — mods list API reachable', async ({ page, request }) => {
    if (isFullStack()) {
      const resp = await request.get('/api/mods/', { timeout: 20_000 });
      expect(resp.status(), await resp.text()).toBeLessThan(500);
    }

    await page.goto('/ai-ecosystem', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    await captureEvidence(page, '05-mod.png');
  });

  test('06 fulfillment — 订单发货后状态流转为已发货', async ({ page, request }) => {
    const apiBase = (process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5001').replace(/\/$/, '');

    if (!isFullStack()) {
      await page.route('**/api/orders/E2E-1001', (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            data: { id: 'E2E-1001', status: 'pending', total: 199.0 },
          }),
        })
      );
      await page.route('**/api/orders/*/fulfill', (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            data: { id: 'E2E-1001', status: 'shipped', tracking_no: 'SF-E2E-001' },
          }),
        })
      );
    }

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });

    const beforeResp = await request.get(`${apiBase}/api/orders/E2E-1001`, { timeout: 15_000 });
    expect(beforeResp.status(), await beforeResp.text()).toBeLessThan(500);
    const beforeBody = await beforeResp.json().catch(() => ({} as any));
    const beforeStatus = String(beforeBody?.data?.status || beforeBody?.status || 'pending');
    expect(['pending', 'paid', 'unfulfilled', 'shipped', 'delivered']).toContain(beforeStatus);

    const fulfillResp = await request.post(`${apiBase}/api/orders/E2E-1001/fulfill`, {
      data: { tracking_no: 'SF-E2E-001', carrier: 'SF' },
      timeout: 15_000,
    });
    expect(fulfillResp.status(), await fulfillResp.text()).toBeLessThan(500);
    const fulfillBody = await fulfillResp.json().catch(() => ({} as any));
    expect(fulfillBody?.success, `fulfill body: ${JSON.stringify(fulfillBody)}`).toBe(true);

    const afterResp = await request.get(`${apiBase}/api/orders/E2E-1001`, { timeout: 15_000 });
    const afterBody = await afterResp.json().catch(() => ({} as any));
    const afterStatus = String(afterBody?.data?.status || afterBody?.status || '');
    expect(['shipped', 'delivered']).toContain(afterStatus);

    await captureEvidence(page, '06-fulfillment.png');
  });
});
