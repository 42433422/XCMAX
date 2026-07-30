import { test, expect } from '@playwright/test';
import { E2E_ACCOUNT_KIND, E2E_PASSWORD, E2E_USER, isFullStack } from './helpers';

test.describe('Login flow', () => {
  test('login page loads without app shell chrome', async ({ page }) => {
    await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('#app')).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test('unauthenticated root eventually shows login or ready shell', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('#app')).toBeVisible();
    const loginVisible = await page
      .locator('input[type="password"], input[autocomplete="current-password"]')
      .first()
      .isVisible()
      .catch(() => false);
    const readyVisible = await page
      .locator('.app-shell.is-ready')
      .isVisible()
      .catch(() => false);
    expect(loginVisible || readyVisible).toBeTruthy();
  });

  test('full stack form login reaches orders and materials without a stuck submit', async ({
    page,
  }) => {
    test.skip(!isFullStack(), 'covered by the mandatory release full-stack job');
    await page.goto('/login?redirect=%2Forders', {
      waitUntil: 'domcontentloaded',
      timeout: 30_000,
    });
    await page.locator('#lv-username').fill(E2E_USER);
    await page.locator('#lv-password').fill(E2E_PASSWORD);
    const loginResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' && /\/api\/auth\/login(?:\?|$)/.test(response.url()),
      { timeout: 45_000 }
    );
    await page.locator('.login-submit').click();

    const loginResponse = await loginResponsePromise;
    const loginText = await loginResponse.text();
    expect(loginResponse.status(), loginText).toBe(200);
    expect(JSON.parse(loginText || '{}')?.success, loginText).toBe(true);
    await expect(page).toHaveURL(/\/orders(?:[?#]|$)/, { timeout: 45_000 });
    await expect(page.locator('.login-submit')).toHaveCount(0);
    await expect(page.locator('#app')).toBeVisible();

    await page.goto('/orders', { waitUntil: 'domcontentloaded', timeout: 20_000 });
    await expect(page).toHaveURL(/\/orders(?:[?#]|$)/);
    await expect(page.locator('#view-orders')).toBeVisible({ timeout: 25_000 });

    await page.goto('/materials', { waitUntil: 'domcontentloaded', timeout: 20_000 });
    await expect(page).toHaveURL(/\/materials(?:[?#]|$)/);
    await expect(page.locator('#view-materials')).toBeVisible({ timeout: 25_000 });
    await expect(page.locator('body')).not.toContainText('正在登录');
  });
});
