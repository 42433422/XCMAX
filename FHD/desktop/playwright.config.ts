import { defineConfig } from '@playwright/test'

/**
 * Playwright-Electron 真实窗口 E2E。
 * 不下载浏览器：_electron 直接驱动 node_modules 里的 Electron 二进制。
 * 运行前需先 `npm run build`（测试以 dist/main.js 为入口，见 package.json scripts.test:e2e）。
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.spec.ts',
  timeout: 120_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
})
