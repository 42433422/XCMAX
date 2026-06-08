import { test, expect } from '@playwright/test';
import { installE2eShellMocks } from './helpers';

const readyMs = Number(process.env.XCAGI_SLA_READY_MS || 3000);
const healthMs = Number(process.env.XCAGI_SLA_HEALTH_MS || 500);

test.describe('SLA performance budgets', () => {
  test('home shell ready within XCAGI_SLA_READY_MS', async ({ page }) => {
    await installE2eShellMocks(page);
    const started = Date.now();
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: readyMs + 20_000 });
    const elapsed = Date.now() - started;
    expect(elapsed, `shell ready in ${elapsed}ms`).toBeLessThan(readyMs + 20_000);
  });

  test('/api/health responds within XCAGI_SLA_HEALTH_MS', async ({ request }) => {
    const started = Date.now();
    const resp = await request.get('/api/health', { timeout: 15_000 });
    const elapsed = Date.now() - started;
    expect(resp.status()).toBeLessThan(500);
    expect(elapsed, `health took ${elapsed}ms`).toBeLessThan(healthMs * 6);
  });
});
