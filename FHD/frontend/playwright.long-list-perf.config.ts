import { defineConfig } from '@playwright/test'

// Dev-only real component fixture, never a production route.
export default defineConfig({
  testDir: './list-perf',
  testMatch: 'long-list.spec.ts',
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 300000,
  reporter: 'list',
  outputDir: process.env.UI_PERF_OUTPUT_DIR || './test-results/list-perf',
  use: {
    browserName: 'chromium',
    baseURL: 'http://127.0.0.1:5001',
    viewport: { width: 1440, height: 900 },
    locale: 'zh-CN',
    launchOptions: { args: ['--no-proxy-server', '--enable-precise-memory-info'] },
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5001 --strictPort',
    url: 'http://127.0.0.1:5001/list-perf/index.html',
    reuseExistingServer: false,
    timeout: 120000,
  },
})
