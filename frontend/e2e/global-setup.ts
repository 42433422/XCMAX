/**
 * 登录并写入 storageState，供 smoke / critical-paths / plan2026 共用会话。
 * 凭证：E2E_USER / E2E_PASSWORD（默认 admin / admin123，与 alembic 种子一致）。
 */
import { chromium, type FullConfig } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const authPath = path.join(__dirname, '.auth', 'user.json');

export default async function globalSetup(config: FullConfig) {
  const baseURL =
    (config.projects[0]?.use?.baseURL as string) ||
    process.env.PLAYWRIGHT_BASE_URL ||
    'http://127.0.0.1:5001';
  const username = process.env.E2E_USER || 'admin';
  const password = process.env.E2E_PASSWORD || 'admin123';

  fs.mkdirSync(path.dirname(authPath), { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext({ baseURL });
  const page = await context.newPage();

  let authed = false;

  try {
    const apiLogin = await context.request.post('/api/auth/login', {
      data: { username, password },
      timeout: 30_000,
    });
    if (apiLogin.ok()) {
      await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
      authed = await page
        .locator('.sidebar')
        .isVisible({ timeout: 25_000 })
        .catch(() => false);
    }
  } catch {
    /* fall through to UI login */
  }

  if (!authed) {
    await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await page.fill('input[name="username"]', username);
    await page.fill('input[name="password"]', password);
    await page.click('button.login-submit');
    await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 30_000 });
    await page.waitForSelector('.sidebar', { timeout: 25_000 });
    authed = true;
  }

  if (!authed) {
    throw new Error(
      `[e2e global-setup] 无法登录 (${username})：请启动 FastAPI :5000（种子 admin/admin123），或设 E2E_VITE_MOCK_API=1 走 Vite 契约 mock`,
    );
  }

  await context.storageState({ path: authPath });
  await browser.close();
}
