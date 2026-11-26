import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './interaction-perf',
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 180000,
  reporter: 'list',
  outputDir: process.env.UI_PERF_OUTPUT_DIR || './test-results/interaction-perf',
  use: {
    browserName: 'chromium',
    baseURL: 'http://127.0.0.1:5001',
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    serviceWorkers: 'block',
    launchOptions: { args: ['--no-proxy-server'] },
  },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 5001 --strictPort',
    url: 'http://127.0.0.1:5001',
    reuseExistingServer: false,
    timeout: 120000,
  },
})
