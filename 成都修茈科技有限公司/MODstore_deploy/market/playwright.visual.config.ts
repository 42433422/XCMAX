import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './visual-regression', forbidOnly: true, retries: 0, workers: 1,
  timeout: 90000, reporter: 'list',
  use: {
    browserName: 'chromium', baseURL: 'http://127.0.0.1:4176',
    deviceScaleFactor: 1, locale: 'zh-CN', timezoneId: 'Asia/Shanghai',
    colorScheme: 'light', reducedMotion: 'reduce', serviceWorkers: 'block',
    launchOptions: { args: ['--no-proxy-server', '--disable-skia-runtime-opts'] },
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4176 --strictPort',
    url: 'http://127.0.0.1:4176', reuseExistingServer: false, timeout: 180000,
    env: { E2E_VITE_MOCK_API: '1' },
  },
})
