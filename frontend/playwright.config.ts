import path from 'path';
import { fileURLToPath } from 'url';
import { defineConfig, devices } from '@playwright/test';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const authFile = path.join(__dirname, 'e2e/.auth/user.json');

/**
 * P0：smoke + critical-paths（5 链）+ plan2026-skeleton（E2E_FULL_STACK=1）。
 * 需 Vite :5001；登录依赖 FastAPI :5000（global-setup 写 e2e/.auth/user.json）。
 */
export default defineConfig({
  testDir: './e2e',
  globalSetup: path.join(__dirname, 'e2e/global-setup.ts'),
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [['line'], ['junit', { outputFile: 'playwright-report/junit.xml' }]] : [['list']],
  timeout: 45_000,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5001',
    storageState: authFile,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
