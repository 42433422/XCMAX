import { test, expect } from '@playwright/test';
import { installE2eShellMocks } from './helpers';

test.describe('Desktop shell contract', () => {
  test('platform-shell deliverable-status API', async ({ request }) => {
    const resp = await request.get('/api/platform-shell/deliverable-status', { timeout: 15_000 });
    expect(resp.status()).toBeLessThan(500);
    if (resp.ok()) {
      const body = await resp.json();
      expect(body?.success).toBeTruthy();
      expect(body?.data).toBeTruthy();
    }
  });

  test('runtime product-sku endpoint', async ({ request }) => {
    const resp = await request.get('/api/runtime/product-sku', { timeout: 15_000 });
    expect(resp.status()).toBeLessThan(500);
  });

  test('app shell renders (Electron-equivalent web shell)', async ({ page }) => {
    await installE2eShellMocks(page);
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('#app')).toBeVisible();
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    const health = await page.evaluate(async () => {
      const r = await fetch('/api/health');
      return r.status;
    });
    expect(health).toBeLessThan(500);
  });
});
